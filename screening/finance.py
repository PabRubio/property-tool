"""Deterministic GBP cash-budget model. No LLM performs or changes calculations."""
import copy
import json
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from statistics import median
from .evidence import enriched_inputs, local_growth, valuation, matched_profile
from .market_evidence import (hydrate_comparables, regional_rent_growth, growth_check,
                              annualised, sample_context, demand_context, property_context)
from .schema import api_property_type
from .providers import numeric

ROOT = Path(__file__).resolve().parent.parent
TAX = json.loads((ROOT / "config/tax_rules.json").read_text())


def money(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def ratio(n, d):
    return round(n / d * 100, 2) if d else None


def stamp_duty(price, a):
    if a.get("sdlt_override") is not None:
        return {"total": a["sdlt_override"], "basis": "Adviser-supplied override", "bands": [], "rules": TAX}
    nonresident = TAX["nonresident_rate"] if a["nonresident"] and price >= TAX["additional_min_price"] else 0
    company = a["buyer_type"] == "company"
    if company and price > TAX["corporate_threshold"] and not a["corporate_relief_confirmed"]:
        rate = TAX["corporate_flat_rate"] + nonresident
        return {"total": money(price * rate), "basis": "Corporate flat rate; rental business relief has not been confirmed", "bands": [{"portion": price, "rate_pct": rate * 100, "tax": money(price * rate)}], "rules": TAX}
    extra = TAX["additional_rate"] if (company or a["additional_property"]) and price >= TAX["additional_min_price"] else 0
    lower, total, bands = 0, Decimal("0"), []
    for upper, base_rate in TAX["bands"]:
        portion = max(0, min(price, upper if upper is not None else price) - lower)
        if portion:
            rate = Decimal(str(base_rate)) + Decimal(str(extra)) + Decimal(str(nonresident))
            tax = Decimal(str(portion)) * rate
            total += tax
            bands.append({"portion": portion, "rate_pct": float(rate * 100), "tax": money(tax)})
        if upper is None or price <= upper:
            break
        lower = upper
    return {"total": money(total), "basis": "England residential bands" + (" + additional property surcharge" if extra else "") + (" + nonresident surcharge" if nonresident else ""), "bands": bands, "rules": TAX}


def payment(principal, annual_rate, months, kind):
    if not principal or kind == "cash":
        return 0
    r = annual_rate / 1200
    if kind == "interest_only":
        return principal * r
    return principal / months if r == 0 else principal * r / (1 - (1 + r) ** -months)


def irr(flows):
    # Annual end-of-period approximation. Return unavailable for ambiguous sign patterns.
    signs = [v > 0 for v in flows if v]
    if not flows or not (min(flows) < 0 < max(flows)) or sum(a != b for a, b in zip(signs, signs[1:])) != 1:
        return None
    def npv(r):
        return sum(v / (1 + r) ** t for t, v in enumerate(flows))
    low, high = -0.99, 10.0
    if npv(low) * npv(high) > 0:
        return None
    for _ in range(160):
        mid = (low + high) / 2
        if npv(mid) > 0:
            low = mid
        else:
            high = mid
    return round((low + high) / 2 * 100, 2)


def monthly_operations(a, rent, month):
    """Rental income and running costs do not require a purchase price."""
    year=month//12
    scheduled=rent*(1+a['rent_growth_pct']/100)**year
    occupancy=0 if month<a['initial_void_months'] else 1-a['void_pct']/100
    collected=scheduled*occupancy;factor=(1+a['cost_growth_pct']/100)**year
    management=collected*a['management_pct']/100
    maintenance=scheduled*a['maintenance_pct']/100
    regular=(a.get('regular_cleaning') or 0)/12*factor
    turnover=(a.get('turnover_cleaning') or 0)/12*factor
    fixed=sum(a.get(k) or 0 for k in ('service_charge','ground_rent','insurance','compliance','fire_safety_annual','licensing_annual','letting_fees','other_annual_costs'))/12*factor+regular+turnover
    void=a['void_cost_monthly']*(1-occupancy)*factor;operating=management+maintenance+fixed+void
    return {'scheduled_rent':scheduled,'lost_rent':scheduled-collected,'collected_rent':collected,
            'management':management,'maintenance':maintenance,'regular_cleaning':regular,'turnover_cleaning':turnover,
            'fixed_costs':fixed,'void_costs':void,'operating_costs':operating,'net_operating_income':collected-operating}


def project(a, price, rent):
    loan = borrowing(a, price)
    debt_payment = payment(loan, a["interest_rate_pct"], a["mortgage_term_years"] * 12, a["financing"])
    first_payment = debt_payment
    balance, rows, cumulative = loan, [], 0.0
    for m in range(a["holding_years"] * 12):
        reset_month = (a.get('fixed_rate_years') or 0) * 12
        rate = a['interest_rate_pct']
        if reset_month and m >= reset_month:
            rate = a.get('rate_after_fix_pct') if a.get('rate_after_fix_pct') is not None else a['interest_rate_pct']+a['rate_stress_pp']
            if m == reset_month:
                debt_payment = payment(balance, rate, max(1,a['mortgage_term_years']*12-m), a['financing'])
        year = m // 12
        operations=monthly_operations(a,rent,m)
        noi=operations['net_operating_income']
        interest = balance * rate / 1200
        principal = min(balance, max(0, debt_payment - interest)) if a["financing"] == "repayment" else 0
        debt = interest + principal
        balance = max(0, balance - principal)
        before_tax = noi - debt
        tax = (a["annual_tax_budget"] or 0) / 12
        cash = before_tax - tax
        cumulative += cash
        rows.append({**operations,"month": m + 1, "year": year + 1,
                     "interest_rate_pct": rate if loan else 0,
                     "interest": interest, "principal": principal, "debt_payment": debt,
                     "cashflow_before_tax": before_tax, "tax_budget": tax, "cashflow": cash,
                     "loan_balance": balance, "cumulative_cashflow": cumulative})
    return rows, loan, first_payment


def borrowing(a, price):
    if a['financing'] == 'cash': return 0
    if a.get('mortgage_amount') is not None: return a['mortgage_amount']
    if a.get('deposit_amount') is not None: return max(0, price-a['deposit_amount'])
    if a.get('deposit_pct') is not None: return price*(1-a['deposit_pct']/100)
    return price*a['ltv_pct']/100


def refurbishment_estimate(evidence):
    d = evidence.get('market', {}).get('build-cost', {})
    if not isinstance(d, dict): return None
    if isinstance(d.get('result'), dict): d = d['result']
    for key in ('total_build_cost', 'build_cost', 'total_cost', 'estimate'):
        value = numeric(d.get(key))
        if value is not None and value > 0: return money(value)
    return None


def analyse(inputs, evidence, mode, include_horizons=True):
    from .comparisons import comparison_summary
    hydrate_comparables(evidence)
    inputs = enriched_inputs(inputs, evidence)
    p, i, a = inputs["property"], inputs["investor"], copy.deepcopy(inputs["assumptions"])
    from .assumptions import apply_cost_policy, assumption_register
    cost_policy = apply_cost_policy(inputs, evidence)
    a['management_pct'] = inputs['assumptions']['management_pct']
    flags = []
    def flag(level, title, detail):
        flags.append({"level": level, "title": title, "detail": detail})
    if inputs.get('enquiry', {}).get('kind') == 'area':
        return {'available': False, 'flags': [], 'missing': ['specific_property']}
    if a['financing'] == 'unknown':
        return {'available': False, 'flags': [{'level':'critical','title':'Financing is not supplied','detail':'Specify cash, or mortgage amount, type and rate.'}], 'missing':['financing']}
    if a['financing'] == 'mortgage_unsure':
        a['financing'] = 'interest_only'
        flag('critical', 'Mortgage repayment type unconfirmed', 'Interest-only is used as an explicit modelling assumption. Repayment borrowing would reduce cash flow; confirm the loan product.')
    if a['financing'] != 'cash' and inputs.get('input_provenance',{}).get('assumptions.interest_rate_pct',{}).get('basis','').startswith('Illustrative default'):
        flag('warning', 'Mortgage interest rate assumed', 'No rate was supplied; the baseline uses 5.5%. The report also compares 4%, 5% and 6%; none is a mortgage offer.')
    if a.get('fixed_rate_years') and a['financing'] != 'cash':
        flag('warning', 'Interest rate resets in the projection', 'After %s years the model uses %s%%, %s. Refinancing terms and fees are not guaranteed.' % (a['fixed_rate_years'], a.get('rate_after_fix_pct') if a.get('rate_after_fix_pct') is not None else a['interest_rate_pct']+a['rate_stress_pp'], 'a supplied scenario' if a.get('rate_after_fix_pct') is not None else 'an explicit '+str(a['rate_stress_pp'])+' percentage-point rise scenario'))
    if a['financing'] == 'interest_only' and a['mortgage_term_years'] < 10:
        flag('warning', 'Mortgage term limits the ownership comparison', 'Periods beyond the supplied interest-only term are not modelled; refinancing terms are unknown.')
        a['holding_years'] = min(a['holding_years'], a['mortgage_term_years'])
    selected = [c for c in inputs["comparables"] if c["selected"]]
    rental_comps = [c for c in selected if c["kind"] == "rent"]
    sold_comps = [c for c in selected if c["kind"] == "sold"]
    area_rent = evidence.get("market", {}).get("monthly_rent")
    rent = a["monthly_rent"]
    rent_basis = "Analyst-selected rent: " + (a["rent_source"] or "source not supplied")
    if rent is None and rental_comps:
        rent = median(c["amount"] for c in rental_comps)
        rent_basis = "Median monthly asking rent of analyst-selected comparables"
    rental_valuation = valuation(evidence, 'rent')
    sale_valuation = valuation(evidence, 'sale')
    rental_evidence = comparison_summary(inputs, evidence, 'rent')
    sales_evidence = comparison_summary(inputs, evidence, 'sold')
    if rent is None and rental_valuation:
        rent = rental_valuation
        rent_basis = 'Property-specific rental valuation [valuation-rent]; modelled asking rent, not a confirmed tenancy'
        flag('warning', 'Rent is an automated estimate', 'Compare with matched listings or a letting-agent opinion before relying on it.')
    if rent is None and rental_evidence['median']:
        rent = rental_evidence['median']
        rent_basis = 'Median of '+str(rental_evidence['count'])+' matched whole-property advertised monthly rents; not achieved rent. See comparison evidence and source links.'
        flag('warning', 'Rent uses researched asking-rent comparisons', 'Condition, furnishing, bills and letting terms require review; advertised rents do not prove achieved rent.')
    if rent is None and area_rent:
        rent = area_rent
        rent_basis = "Provisional PropertyData area asking-rent average"
        if evidence.get('market', {}).get('rent_bedroom_filter_omitted'):
            rent_basis += ' across all bedroom counts; not a matched %s-bedroom estimate' % p['bedrooms']
        flag("critical", "Rent is based only on the local average", "Obtain matched rental comparables or an agent opinion before relying on this figure.")
    if rent is None:
        return {"available": False, "flags": [{"level": "critical", "title": "A rent estimate is required", "detail": "Enter monthly rent, select rental comparables, or gather live evidence."}], "missing": ["monthly_rent"]}
    price = a["purchase_price"] if a["purchase_price"] is not None else p["asking_price"]
    price_basis = 'Client / analyst purchase price' if a['purchase_price'] is not None else 'Client-supplied listing / offer price'
    if price is None:
        price = sale_valuation
        price_basis = 'Illustrative purchase at the automated sale valuation [valuation-sale]; no asking or agreed price supplied'
        if price is None and sales_evidence['median']:
            price = sales_evidence['median']
            price_basis = 'Illustrative purchase at the median of matched completed-sale comparisons; no asking or agreed price supplied'
        if price is None:
            return {'available': False, 'flags': flags+[{'level':'critical','title':'Purchase price unavailable','detail':'No supplied price or usable property valuation. Supply a proposed purchase price.'}], 'missing':['purchase_price'],
                    'resolved_inputs':{'monthly_rent':rent,'rent_basis':rent_basis}}
        flag('critical', 'Purchase price is a valuation scenario', 'There is no known listing or agreed price; returns use an automated estimate as the purchase assumption.')
    if a.get('mortgage_amount') is not None and a['financing'] != 'cash' and a['mortgage_amount'] >= price:
        return {'available': False, 'flags': [{'level':'critical','title':'Mortgage exceeds purchase assumption','detail':'Review the mortgage amount and purchase price.'}], 'missing':['mortgage_amount']}
    a["monthly_rent"], a["purchase_price"] = rent, price
    current_value = sale_valuation or price
    value_basis = 'Property-specific sale valuation [valuation-sale]' if sale_valuation else 'Purchase price used as a proxy because no property-specific sale valuation is available'
    if sale_valuation and abs(price / sale_valuation - 1) > .15:
        flag('warning', 'Purchase price differs materially from the sale valuation', 'Purchase costs use the supplied price. Future sale scenarios start from the property-specific valuation; check matched sales before relying on it.')
    if a.get('mortgage_amount') is not None and a['financing'] != 'cash': a['ltv_pct'] = a['mortgage_amount'] / price * 100
    growth = local_growth(evidence)
    crosscheck = growth_check(evidence)
    regional_rent = regional_rent_growth(evidence)
    context = property_context(inputs, evidence)
    flags.extend(context['flags'])
    def unprovided(key):
        basis = inputs.get('input_provenance', {}).get('assumptions.'+key, {}).get('basis', '')
        return a.get(key) is None or (a.get(key) == 0 and basis.startswith('Illustrative default'))
    price_growth_basis = 'Client / analyst growth scenario; not a forecast'
    if unprovided('price_growth_pct'):
        a['price_growth_pct'] = 0
        price_growth_basis = 'No growth assumed: insufficient local history to estimate a trend'
        for source, series in [('growth', growth), ('growth-psf', crosscheck['psf_series'])]:
            rate = annualised(series)
            if rate is not None:
                a['price_growth_pct'] = rate
                measure = 'local prices' if source == 'growth' else 'local sold prices per square foot'
                price_growth_basis = 'Scenario extends annualised '+measure+' change, '+series[0]['month']+' to '+series[-1]['month']+' ['+source+']. Past growth is not a forecast.'
                break
    if crosscheck['material_difference']:
        flag('warning', 'Historical price-growth measures disagree', 'Average-price and sold-price-per-square-foot trends differ over the same period. Property mix can affect the comparison; the report does not average these rates or treat either as a forecast.')
    rent_growth_basis = 'Client / analyst rent-growth scenario; not a forecast'
    if unprovided('rent_growth_pct'):
        a['rent_growth_pct'] = regional_rent['rate'] if regional_rent['rate'] is not None else 0
        rent_growth_basis = regional_rent['reason']
        if regional_rent['rate'] is None:
            flag('warning', 'Rent-growth evidence unavailable', regional_rent['reason']+'. Cash flows use an explicit no-growth fallback until evidence or an analyst assumption is supplied.')
    no_refurbishment = a['refurb_level'] == 'none'
    reference_refurb = None if no_refurbishment else refurbishment_estimate(evidence)
    planned = a.get('refurbishment_planned', False) or (a.get('refurbishment') or 0) > 0
    if planned and not context['planning']['requested']:
        flag('warning', 'Planning context has not been researched', 'Works are planned. Review the local authority records and required consents; saved evidence contains no planning search.')
    refurb_basis = 'No refurbishment selected in this brief; refurbishment costs and value uplift are excluded'
    if planned:
        refurb_basis = 'Client / analyst refurbishment budget'
        if a['refurbishment'] is None:
            a['refurbishment'] = reference_refurb
            refurb_basis = 'Provider reference estimate included because works are planned; not a contractor quote'
        if a['refurbishment'] is None:
            flag('critical', 'Planned refurbishment cost is unknown', 'No budget or usable estimate. Costs exclude the planned work and returns are incomplete.')
            refurb_basis = 'Unknown: planned works excluded until priced'
    else: a['refurbishment'] = 0
    a['refurbishment'] = a['refurbishment'] or 0
    uplift = 0
    uplift_basis = 'No refurbishment selected in this brief'
    uplift_refs = ['assumptions']
    if planned:
        fact = evidence.get('researched_facts',{}).get('refurbishment.uplift',{})
        researched = fact.get('value',{})
        researched_value = researched.get('after_works_value') if isinstance(researched,dict) else None
        cited_comps=set(researched.get('comparable_source_ids',[])) if isinstance(researched,dict) else set()
        evidenced_comps=[row for row in sales_evidence['matched'] if cited_comps.intersection(row.get('source_ids') or [row.get('source_id')])]
        if a.get('refurb_value_uplift') is not None:
            uplift = a['refurb_value_uplift']
            uplift_basis = 'Supplied refurbishment value-increase assumption; not a guaranteed valuation'
        elif isinstance(researched_value,(int,float)) and not isinstance(researched_value,bool) and researched_value > 0 and len(evidenced_comps) >= 3:
            uplift = researched_value-current_value
            uplift_basis = 'After-works value scenario informed by cited renovated comparisons: '+str(researched.get('basis') or fact.get('text',''))
            uplift_refs = fact.get('source_ids',[])
        else:
            uplift = a['refurbishment'] * a['refurb_uplift_pct_of_cost']/100
            uplift_basis = ('Explicit fallback modelling assumption: %s%% of the refurbishment budget is added to property value once works finish. Contingency and safety / purchase costs do not create uplift. This is not a researched market return or guaranteed recovery of spend.' % a['refurb_uplift_pct_of_cost'])
        if not a['refurbishment']:
            flag('critical', 'Refurbishment remains unpriced', 'Planned works have no usable budget. A cost-linked value uplift cannot be quantified; this scenario is incomplete.')
    completion_month = a['initial_void_months']
    if (a.get('fire_safety_upfront') is None or a.get('fire_safety_annual') is None or
        cost_policy['strategy'] == 'hmo' and a.get('licensing_annual') is None):
        flag('warning', 'Fire safety / licensing costs are not fully priced', 'The compliance allowance covers routine checks only. Additional fire works, specialist checks and applicable licensing are excluded where unpriced; returns may be lower.')
    if p['property_type'] in ('bungalow', 'converted_flat', 'studio'):
        flag('warning', 'Valuation uses a broader property category', 'Provider model uses '+api_property_type(p).replace('_',' ')+'; check comparables for this specific subtype.')
    if a["financing"] == "cash":
        a["mortgage_fees"] = 0
    sdlt = stamp_duty(price, a)
    refurb = a["refurbishment"] * (1 + a["contingency_pct"] / 100)
    acquisition = sdlt["total"] + a["legal_fees"] + a["survey_fees"] + a["other_purchase_costs"] + (a.get('fire_safety_upfront') or 0)
    project_cost = price + acquisition + refurb
    rows, loan, debt = project(a, price, rent)
    a['ltv_pct'] = loan/price*100 if loan else 0
    cash_required = project_cost - loan + a["mortgage_fees"] + a["cash_reserve"]
    # Stabilised first-year prices, no initial refurbishment vacancy.
    stable_a = dict(a, initial_void_months=0, holding_years=1)
    stable, _, _ = project(stable_a, price, rent)
    stable_noi = sum(r["net_operating_income"] for r in stable)
    stable_cash = sum(r["cashflow_before_tax"] for r in stable)
    annuals = []
    sums = [k for k in rows[0] if k not in ("month", "year", "loan_balance", "cumulative_cashflow", "interest_rate_pct")]
    for y in range(1, a["holding_years"] + 1):
        yr = rows[(y - 1) * 12:y * 12]
        ann = {k: money(sum(r[k] for r in yr)) for k in sums}
        ann.update(year=y, loan_balance=money(yr[-1]["loan_balance"]), cumulative_cashflow=money(yr[-1]["cumulative_cashflow"]),
                   property_value=money(current_value * (1 + a["price_growth_pct"] / 100) ** y +
                                        (uplift * (1+a['price_growth_pct']/100) ** (y-completion_month/12) if y*12 >= completion_month else 0)))
        annuals.append(ann)
    sale_price = annuals[-1]["property_value"]
    sale_costs = sale_price * a["selling_fee_pct"] / 100 + a["sale_legal_fees"] + a["early_repayment_fee"]
    sale_proceeds = sale_price - sale_costs - rows[-1]["loan_balance"] - (a["sale_tax_budget"] or 0)
    no_uplift_sale = current_value * (1+a['price_growth_pct']/100) ** a['holding_years']
    no_uplift_proceeds = no_uplift_sale*(1-a['selling_fee_pct']/100)-a['sale_legal_fees']-a['early_repayment_fee']-rows[-1]['loan_balance']-(a['sale_tax_budget'] or 0)
    cash_flows = [-cash_required] + [v["cashflow"] for v in annuals]
    cash_flows[-1] += sale_proceeds + a["cash_reserve"]
    total_profit = sum(cash_flows)
    minimum_cumulative = min(0, min(r["cumulative_cashflow"] for r in rows))
    additional_funding = max(0, -minimum_cumulative - a["cash_reserve"])
    rent_gap = ratio(rent - area_rent, area_rent) if area_rent else None
    sold_median = median(c["amount"] for c in sold_comps) if sold_comps else None
    net_yield = ratio(stable_noi, project_cost)
    metrics = {"purchase_price": price, "monthly_rent": money(rent), "gross_yield_pct": ratio(rent * 12, price),
               "floor_area_sqft": money(p['floor_area_sqm'] * 10.7639104167) if p.get('floor_area_sqm') else None,
               "purchase_price_per_sqft": money(price / (p['floor_area_sqm'] * 10.7639104167)) if p.get('floor_area_sqm') else None,
               "net_yield_on_price_pct": ratio(stable_noi, price), "net_yield_on_cost_pct": net_yield,
               "stabilised_noi": money(stable_noi), "monthly_cashflow_before_tax": money(stable_cash / 12),
               "monthly_cashflow_after_tax_budget": money(stable_cash / 12 - (a["annual_tax_budget"] or 0) / 12) if a["annual_tax_budget"] is not None else None,
               "cash_on_cash_pct": ratio(stable_cash, cash_required), "first_year_cashflow": annuals[0]["cashflow_before_tax"],
               "loan": money(loan), "monthly_debt_payment": money(debt), "cash_required": money(cash_required),
               "total_property_cost": money(project_cost), "refurbishment_with_contingency": money(refurb),
               "acquisition_costs": money(acquisition), "dscr": round(stable_noi / (debt * 12), 2) if debt else None,
               "rent_vs_area_pct": rent_gap, "selected_sold_median": sold_median,
               "price_vs_selected_sales_pct": ratio(price - sold_median, sold_median) if sold_median else None,
               "asking_price_per_sqft": money(p["asking_price"] / (p["floor_area_sqm"] * 10.7639104167)) if p["floor_area_sqm"] and p["asking_price"] else None,
               "additional_cash_needed": money(additional_funding)}
    scenarios = []
    for label, rent_factor, rate_add, void_add, cost_factor in [
        ("Base", 1, 0, 0, 1), ("Lower rent", 1-a["rent_stress_pct"]/100, 0, 0, 1),
        ("Higher interest", 1, a["rate_stress_pp"], 0, 1), ("Higher operating costs", 1, 0, 0, 1+a["cost_stress_pct"]/100),
        ("90% occupancy", 1, 0, 10-a["void_pct"], 1),
        ("Combined downside", 1-a["rent_stress_pct"]/100, a["rate_stress_pp"], 5, 1+a["cost_stress_pct"]/100)]:
        sa = dict(stable_a, interest_rate_pct=a["interest_rate_pct"]+rate_add, void_pct=min(100, a["void_pct"]+void_add))
        for k in ("management_pct", "maintenance_pct", "insurance", "compliance", "fire_safety_annual", "licensing_annual", "letting_fees", "other_annual_costs", "void_cost_monthly", "service_charge", "ground_rent", "regular_cleaning", "turnover_cleaning"):
            sa[k] = (sa[k] or 0) * cost_factor
        sr, _, _ = project(sa, price, rent * rent_factor)
        scenarios.append({"name": label, "monthly_rent": money(rent*rent_factor), "interest_rate_pct": sa["interest_rate_pct"] if loan else None,
                          "rent_change_pct": round((rent_factor-1)*100, 2), "rate_change_pp": rate_add if loan else 0,
                          "cost_change_pct": round((cost_factor-1)*100, 2),
                          "void_pct": sa["void_pct"], "monthly_cashflow": money(sum(r["cashflow_before_tax"] for r in sr)/12)})
    denom = (1-a["void_pct"]/100)*(1-a["management_pct"]/100)-a["maintenance_pct"]/100
    fixed = stable[0]["fixed_costs"] + stable[0]["void_costs"]
    metrics["break_even_rent"] = money((fixed+debt)/denom) if denom > 0 else None
    tests = [
        {"label": "Net yield on total cost", "target": a["min_net_yield_pct"], "actual": round(stable_noi / project_cost * 100, 4), "unit": "%", "passes": stable_noi / project_cost * 100 >= a["min_net_yield_pct"]},
        {"label": "Monthly cash flow before income tax", "target": a["min_monthly_cashflow"], "actual": metrics["monthly_cashflow_before_tax"], "unit": "GBP", "passes": stable_cash / 12 >= a["min_monthly_cashflow"]}]
    if mode == "demo":
        flag("critical", "Demonstration only", "All example evidence is fictional. This report must not be used to assess a real property.")
    if not evidence.get("country_verified"):
        flag("warning", "England location not independently verified", "The country is supplied by the user; verify the address before relying on England tax rules.")
    if p["tenure"] == "unknown":
        flag("critical", "Ownership type is unknown", "Confirm freehold / leasehold and any annual charges.")
    if p["tenure"] != "freehold":
        for key, label in [("service_charge", "Service charge"), ("ground_rent", "Ground rent")]:
            if a[key] is None:
                flag("critical", label + " is unknown", "Temporarily modelled at £0; returns may be overstated. Obtain current charges and planned major works.")
        if p["lease_years"] is None:
            flag("critical", "Lease length is unknown", "Obtain the remaining lease length and extension terms.")
        elif p["lease_years"] < 85:
            flag("warning", "Lease requires specialist review", "The remaining term may affect lender availability and extension costs; the model includes no extension quote.")
    elif a["service_charge"] is None:
        flag("warning", "Estate / service charges not confirmed", "Modelled at £0 for now. Confirm whether this freehold property has estate or management charges.")
    if api_property_type(p) == "flat" and p["cladding_status"] in ("unknown", "concern"):
        flag("critical", "Building safety needs review", "Obtain applicable fire safety / cladding evidence and confirm lender requirements.")
    if p["epc_rating"] == "unknown":
        flag("warning", "EPC not confirmed", "Confirm the certificate, floor area and any improvement works required for letting.")
    elif p["epc_rating"] in ("F", "G"):
        flag("critical", "Low EPC rating", "Confirm current letting eligibility, exemptions and improvement costs before proceeding.")
    if not a["rent_source"] and not rental_comps and not rental_valuation and not rental_evidence['median']:
        flag("warning", "Selected rent has no property-specific evidence", "Add an agent opinion or matched comparables; an asking rent is not proof of achieved rent.")
    if max(len(rental_comps),rental_evidence['count']) < 3:
        flag("warning", "Limited matched rental evidence", "Fewer than three analyst-selected or sufficiently matched researched rental comparisons. Weak area listings do not establish achievable rent.")
    if max(len(sold_comps),sales_evidence['count']) < 3:
        flag("warning", "Limited matched sold evidence", "Fewer than three analyst-selected or sufficiently matched researched sales within 18 months; an area average does not establish this property's value.")
    for c in selected:
        if not c["date"] or not c["source_url"]:
            flag("warning", "Comparable lacks a date or source link", c["address"])
        elif (date.today()-date.fromisoformat(c["date"])).days > (180 if c["kind"] == "rent" else 730):
            flag("warning", "Older comparable evidence", c["address"] + ": review market changes since the evidence date.")
        if c["bedrooms"] is not None and c["bedrooms"] != p["bedrooms"]:
            flag("warning", "Comparable bedroom mismatch", c["address"] + ": explain the adjustment before relying on this comparison.")
    if rent_gap is not None and abs(rent_gap) > 15:
        flag("warning", "Selected rent differs materially from the area baseline", "The difference is %.1f%%. Record property-specific reasons for the gap." % rent_gap)
    if a["financing"] != "cash" and not a["finance_source"]:
        flag("warning", "Mortgage terms are assumptions", "Replace illustrative rates and fees with a broker quote. A supplied fixed period uses the disclosed reset scenario; otherwise the base rate is held constant.")
    term_basis = inputs.get('input_provenance', {}).get('assumptions.mortgage_term_years', {}).get('basis', '')
    if a['financing'] != 'cash' and term_basis.startswith('Illustrative default'):
        flag('warning', 'Full mortgage term assumed', 'No full mortgage term was supplied; calculations use a %s-year modelling assumption. Confirm the actual loan term; this is not the fixed-rate deal length.' % a['mortgage_term_years'])
    if not a["cost_source"]:
        flag("warning", "Running costs need confirmation", "Default budgets are illustrative. Confirm charges, insurance, management and repair costs.")
    for key, label in [('regular_cleaning', 'Regular cleaning'), ('turnover_cleaning', 'Cleaning between tenancies')]:
        if a.get(key) is None:
            flag('warning', label+' budget unconfirmed', 'No landlord-paid annual budget supplied. Excluded from the calculation, not included in maintenance. Confirm responsibility, frequency and a quote; enter zero only if no landlord cost applies.')
    if a["new_lease"] and a["sdlt_override"] is None:
        flag("critical", "New lease tax needs review", "Lease-rent net present value is not included; supply an adviser-confirmed total purchase tax.")
    if a["buyer_type"] == "company" and price > 500000:
        flag("warning", "Company purchase relief and annual charges need review", "Confirm rental business relief conditions and any ATED filing / charge with an adviser.")
    if a["annual_tax_budget"] is None:
        flag("info", "Income tax is excluded", "Cash-flow headlines are before personal or company income tax. Enter an adviser-supplied annual tax budget to show a separate after-budget figure.")
    if a["sale_tax_budget"] is None:
        flag("info", "Tax on disposal is excluded", "Exit proceeds and projected return exclude capital gains / corporation tax on sale.")
    if (date.today()-date.fromisoformat(TAX["verified_on"])).days > 90:
        flag("warning", "Tax rules need refreshing", "The configured SDLT rules were last verified on " + TAX["verified_on"])
    if scenarios[-1]["monthly_cashflow"] < 0:
        flag("warning", "Combined downside loses cash", "The lower-rent, higher-cost and higher-interest scenario requires additional funding.")
    if additional_funding > 0:
        flag("critical", "Cash buffer does not cover projected deficits", "An additional £%.2f is needed beyond the initial cash buffer." % additional_funding)
    if sale_proceeds < 0:
        flag("critical", "Sale proceeds do not cover exit liabilities", "The exit scenario requires additional cash to repay the loan, selling costs and any tax budget.")
    if not p["listing_checked"]:
        flag("warning", "Listing availability not checked", "Confirm the property is still available and record the date of the check.")
    if evidence.get("retrieved_at") and (date.today()-date.fromisoformat(evidence["retrieved_at"][:10])).days > 30:
        flag("warning", "Stored evidence is over thirty days old", "Gather fresh data and review current asking rents and listing availability.")
    if p["listing_checked"] and (date.today()-date.fromisoformat(p["listing_checked"])).days > 30:
        flag("warning", "Listing availability needs refreshing", "The listing was last checked over 30 days ago.")
    if evidence.get("errors"):
        flag("warning", "Some data requests failed or were unavailable", "Review the evidence request log; no failed request has been replaced with demonstration data.")
    if evidence.get('research',{}).get('status') in ('failed','partial_failure','unavailable','incomplete'):
        flag('warning', 'Fallback research is incomplete', 'One or more live research tasks could not complete. Consult the separate evidence document; unresolved fields are not cleared checks. Retry generation after the provider issue is resolved.')
    passes = all(t["passes"] for t in tests)
    verdict = "Meets configured financial targets" if passes else "Below one or more financial targets"
    if any(f["level"] == "critical" for f in flags):
        verdict = "Provisional — material evidence gaps" if mode != "demo" else "DEMO — fictional example"
    profile = matched_profile({'inputs': inputs, 'evidence': evidence})
    profile_estimate = numeric(profile.get('estimate', {}).get('estimate'))
    model = {"available": True, "version": 5, "metrics": metrics, "rent_basis": rent_basis, "effective_assumptions": a,
            "cost_policy":cost_policy, "assumption_register":assumption_register(inputs,a),
            "funding":{'cash_available':i['cash_budget'], 'cash_required':money(cash_required+additional_funding),
                       'extra_cash_needed':money(max(0,cash_required+additional_funding-i['cash_budget'])) if i['cash_budget'] is not None else None},
            "refurbishment_uplift":{'included':planned,'amount':money(uplift),'basis':uplift_basis,'source_ids':uplift_refs,
                                    'completion_month':completion_month,'after_works_value':money(current_value+uplift),
                                    'no_uplift_sale_price':money(no_uplift_sale),'no_uplift_sale_proceeds':money(no_uplift_proceeds),
                                    'no_uplift_total_profit':money(total_profit-(sale_proceeds-no_uplift_proceeds))},
            "rental_evidence": rental_evidence, "sales_evidence": sales_evidence,
            "effective_property": p, "price_basis": price_basis, "price_growth_basis": price_growth_basis,
            "starting_value": current_value, "value_basis": value_basis,
            "rent_growth_basis": rent_growth_basis, "local_growth": growth,
            "growth_crosscheck": crosscheck, "regional_rent_growth": regional_rent, "property_context": context,
            "market_context": {"rent_sample": sample_context(evidence, 'rents'),
                               "sold_sample": sample_context(evidence, 'sold-prices' if evidence.get('raw', {}).get('sold-prices') else 'sold-prices-per-sqf'),
                               "sales_demand": demand_context(evidence, 'demand'),
                               "rental_demand": demand_context(evidence, 'demand-rent')},
            "valuations": {"sale": sale_valuation, "rent": rental_valuation, "profile_estimate": profile_estimate},
            "refurbishment_reference": {"estimate": reference_refurb, "basis": 'No refurbishment selected' if no_refurbishment else evidence.get('refurbishment_basis', a['refurb_level'].replace('refurb_', '')+' refurbishment; '+a['refurb_finish']+' finish'), "included": planned, "cost_basis": refurb_basis, "requested": not no_refurbishment},
            "sdlt": sdlt, "flags": flags, "tests": tests, "verdict": verdict,
            "monthly": [{k: money(v) if k not in ("month", "year") else v for k,v in r.items()} for r in rows],
            "annual": annuals, "scenarios": scenarios,
            "exit": {"sale_price": money(sale_price), "selling_costs": money(sale_costs), "loan_to_repay": money(rows[-1]["loan_balance"]),
                     "sale_proceeds": money(sale_proceeds), "returned_cash_reserve": a["cash_reserve"],
                     "total_profit": money(total_profit), "total_return_pct": ratio(total_profit, cash_required),
                     "annual_irr_pct": irr(cash_flows), "cash_flows": [money(v) for v in cash_flows]},
            "methodology": [
                "Gross yield = scheduled annual rent / purchase price. Net yield on cost = stabilised rent after vacancies and operating budgets / (price + SDLT + acquisition fees + refurbishment including contingency).",
                "Cash-on-cash = stabilised annual cash flow after mortgage payments, before income tax / initial cash required including the cash buffer and finance fees.",
                "Monthly projections start at completion. Initial empty months replace normal occupancy; ongoing vacancy is a fractional monthly allowance after those months. Percentage management fees use collected rent; maintenance uses scheduled rent.",
                "Repayment debt includes interest and principal; interest-only principal is repaid at exit. A supplied fixed period resets the rate at expiry using the supplied rate or the explicit stress rise, and repayment payments use the remaining term. Otherwise the base rate stays constant. Refurbishment value uplift is added once, after the initial empty months. Rent uses the selected rent; no additional rent uplift or refinancing is automatic.",
                "All costs are cash budgets including VAT where supplied. Maintenance / major works allowances are treated as spent. The separate initial cash buffer is returned at exit, with deficits funded from that buffer first.",
                "Targets and cost defaults are editable screening assumptions, not industry standards. Sold comparison uses selected unadjusted transaction prices and requires an analyst to assess size, age, condition and location.",
                "Income and sale taxes use optional adviser-supplied amounts only. Annual IRR assumes year-end cash flows and is unavailable for ambiguous cash-flow patterns. Projections and stress scenarios are assumptions, not forecasts."
            ]}

    if include_horizons:
        from .decision import purchase_guidance, operating_costs
        model['purchase_guidance'] = purchase_guidance(inputs, model)
        from .evidence import property_history
        history = property_history({'inputs':inputs,'evidence':evidence})
        ceiling = model['purchase_guidance']['yield_price_ceiling']
        model['decision_comparisons'] = {
            'cash_budget_shortfall': money(max(0,cash_required+additional_funding-i['cash_budget'])) if i['cash_budget'] is not None else None,
            'net_yield_target_gap_pp': round(a['min_net_yield_pct']-net_yield,2),
            'purchase_price_above_yield_ceiling': money(price-ceiling) if ceiling else None,
            'last_subject_sale': history[0] if history else None,
            'price_change_since_last_subject_sale_pct': ratio(price-history[0]['amount'],history[0]['amount']) if history else None}
        model['operating_costs'] = operating_costs(inputs, model)
        model['rate_comparisons'] = []
        if loan:
            for rate in (4,5,6):
                trial, _, _ = project(dict(stable_a, interest_rate_pct=rate, fixed_rate_years=None), price, rent)
                model['rate_comparisons'].append({'rate_pct':rate, 'monthly_payment':money(trial[0]['debt_payment']), 'monthly_cashflow':money(sum(x['cashflow_before_tax'] for x in trial)/12)})
        stress_rate = a['interest_rate_pct']+a['rate_stress_pp']
        model['interest_coverage'] = {'base_pct':ratio(rent*12,loan*a['interest_rate_pct']/100) if loan else None,
                                      'stress_pct':ratio(rent*12,loan*stress_rate/100) if loan else None, 'stress_rate_pct':stress_rate,
                                      'basis':'Scheduled annual rent / annual interest on initial borrowing. Stress uses the stated rate plus the configured percentage-point rise; not a lender affordability decision.'}
        model['horizons'] = []
        for years in sorted({3, 5, 10, a['holding_years']}):
            if a['financing'] == 'interest_only' and years > a['mortgage_term_years']:
                model['horizons'].append({'years': years, 'available': False, 'reason': 'Beyond the supplied interest-only mortgage term; refinancing terms required'})
                continue
            scenario_inputs = copy.deepcopy(inputs)
            scenario_inputs['assumptions']['holding_years'] = years
            result = analyse(scenario_inputs, evidence, mode, include_horizons=False)
            model['horizons'].append({'years': years, 'available': result['available'],
                                     'rental_income': money(sum(x['collected_rent'] for x in result['annual'])),
                                     'operating_costs': money(sum(x['operating_costs'] for x in result['annual'])),
                                     'debt_paid': money(sum(x['debt_payment'] for x in result['annual'])),
                                     'rental_cashflow': money(sum(x['cashflow'] for x in result['annual'])),
                                     'additional_cash_needed': result['metrics']['additional_cash_needed'],
                                     'annual': result['annual'], 'monthly': result['monthly'], 'exit': result['exit']})
    return model
