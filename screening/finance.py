"""Deterministic GBP cash-budget model. No LLM performs or changes calculations."""
import copy
import json
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from statistics import median

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


def project(a, price, rent):
    loan = 0 if a["financing"] == "cash" else price * a["ltv_pct"] / 100
    debt_payment = payment(loan, a["interest_rate_pct"], a["mortgage_term_years"] * 12, a["financing"])
    balance, rows, cumulative = loan, [], 0.0
    for m in range(a["holding_years"] * 12):
        year = m // 12
        scheduled = rent * (1 + a["rent_growth_pct"] / 100) ** year
        initial_empty = m < a["initial_void_months"]
        occupancy = 0 if initial_empty else 1 - a["void_pct"] / 100
        collected = scheduled * occupancy
        factor = (1 + a["cost_growth_pct"] / 100) ** year
        # No extra annual cost inflation on percentage fees: rent growth already changes them.
        management = collected * a["management_pct"] / 100
        maintenance = scheduled * a["maintenance_pct"] / 100
        fixed = sum(a.get(k) or 0 for k in ("service_charge", "ground_rent", "insurance", "compliance", "letting_fees", "other_annual_costs")) / 12 * factor
        void_cost = a["void_cost_monthly"] * (1 - occupancy) * factor
        operating = management + maintenance + fixed + void_cost
        noi = collected - operating
        interest = balance * a["interest_rate_pct"] / 1200
        principal = min(balance, max(0, debt_payment - interest)) if a["financing"] == "repayment" else 0
        debt = interest + principal
        balance = max(0, balance - principal)
        before_tax = noi - debt
        tax = (a["annual_tax_budget"] or 0) / 12
        cash = before_tax - tax
        cumulative += cash
        rows.append({"month": m + 1, "year": year + 1, "scheduled_rent": scheduled,
                     "lost_rent": scheduled - collected, "collected_rent": collected,
                     "management": management, "maintenance": maintenance, "fixed_costs": fixed,
                     "void_costs": void_cost, "operating_costs": operating, "net_operating_income": noi,
                     "interest": interest, "principal": principal, "debt_payment": debt,
                     "cashflow_before_tax": before_tax, "tax_budget": tax, "cashflow": cash,
                     "loan_balance": balance, "cumulative_cashflow": cumulative})
    return rows, loan, debt_payment


def analyse(inputs, evidence, mode):
    p, i, a = inputs["property"], inputs["investor"], copy.deepcopy(inputs["assumptions"])
    flags = []
    def flag(level, title, detail):
        flags.append({"level": level, "title": title, "detail": detail})
    selected = [c for c in inputs["comparables"] if c["selected"]]
    rental_comps = [c for c in selected if c["kind"] == "rent"]
    sold_comps = [c for c in selected if c["kind"] == "sold"]
    area_rent = evidence.get("market", {}).get("monthly_rent")
    rent = a["monthly_rent"]
    rent_basis = "Analyst-selected rent: " + (a["rent_source"] or "source not supplied")
    if rent is None and rental_comps:
        rent = median(c["amount"] for c in rental_comps)
        rent_basis = "Median monthly asking rent of analyst-selected comparables"
    if rent is None and area_rent:
        rent = area_rent
        rent_basis = "Provisional PropertyData area asking-rent average"
        flag("critical", "Rent is based only on the local average", "Obtain matched rental comparables or an agent opinion before relying on this figure.")
    if rent is None:
        return {"available": False, "flags": [{"level": "critical", "title": "A rent estimate is required", "detail": "Enter monthly rent, select rental comparables, or gather live evidence."}], "missing": ["monthly_rent"]}
    price = a["purchase_price"] if a["purchase_price"] is not None else p["asking_price"]
    a["monthly_rent"], a["purchase_price"] = rent, price
    if a["financing"] == "cash":
        a["mortgage_fees"] = 0
    sdlt = stamp_duty(price, a)
    refurb = a["refurbishment"] * (1 + a["contingency_pct"] / 100)
    acquisition = sdlt["total"] + a["legal_fees"] + a["survey_fees"] + a["other_purchase_costs"]
    project_cost = price + acquisition + refurb
    rows, loan, debt = project(a, price, rent)
    cash_required = project_cost - loan + a["mortgage_fees"] + a["cash_reserve"]
    # Stabilised first-year prices, no initial refurbishment vacancy.
    stable_a = dict(a, initial_void_months=0, holding_years=1)
    stable, _, _ = project(stable_a, price, rent)
    stable_noi = sum(r["net_operating_income"] for r in stable)
    stable_cash = sum(r["cashflow_before_tax"] for r in stable)
    annuals = []
    sums = [k for k in rows[0] if k not in ("month", "year", "loan_balance", "cumulative_cashflow")]
    for y in range(1, a["holding_years"] + 1):
        yr = rows[(y - 1) * 12:y * 12]
        ann = {k: money(sum(r[k] for r in yr)) for k in sums}
        ann.update(year=y, loan_balance=money(yr[-1]["loan_balance"]), cumulative_cashflow=money(yr[-1]["cumulative_cashflow"]),
                   property_value=money(price * (1 + a["price_growth_pct"] / 100) ** y))
        annuals.append(ann)
    sale_price = annuals[-1]["property_value"]
    sale_costs = sale_price * a["selling_fee_pct"] / 100 + a["sale_legal_fees"] + a["early_repayment_fee"]
    sale_proceeds = sale_price - sale_costs - rows[-1]["loan_balance"] - (a["sale_tax_budget"] or 0)
    cash_flows = [-cash_required] + [v["cashflow"] for v in annuals]
    cash_flows[-1] += sale_proceeds + a["cash_reserve"]
    total_profit = sum(cash_flows)
    minimum_cumulative = min(0, min(r["cumulative_cashflow"] for r in rows))
    additional_funding = max(0, -minimum_cumulative - a["cash_reserve"])
    rent_gap = ratio(rent - area_rent, area_rent) if area_rent else None
    sold_median = median(c["amount"] for c in sold_comps) if sold_comps else None
    net_yield = ratio(stable_noi, project_cost)
    metrics = {"purchase_price": price, "monthly_rent": money(rent), "gross_yield_pct": ratio(rent * 12, price),
               "net_yield_on_price_pct": ratio(stable_noi, price), "net_yield_on_cost_pct": net_yield,
               "stabilised_noi": money(stable_noi), "monthly_cashflow_before_tax": money(stable_cash / 12),
               "monthly_cashflow_after_tax_budget": money(stable_cash / 12 - (a["annual_tax_budget"] or 0) / 12) if a["annual_tax_budget"] is not None else None,
               "cash_on_cash_pct": ratio(stable_cash, cash_required), "first_year_cashflow": annuals[0]["cashflow_before_tax"],
               "loan": money(loan), "monthly_debt_payment": money(debt), "cash_required": money(cash_required),
               "total_property_cost": money(project_cost), "refurbishment_with_contingency": money(refurb),
               "acquisition_costs": money(acquisition), "dscr": round(stable_noi / (debt * 12), 2) if debt else None,
               "rent_vs_area_pct": rent_gap, "selected_sold_median": sold_median,
               "price_vs_selected_sales_pct": ratio(price - sold_median, sold_median) if sold_median else None,
               "asking_price_per_sqft": money(p["asking_price"] / (p["floor_area_sqm"] * 10.7639104167)) if p["floor_area_sqm"] else None,
               "additional_cash_needed": money(additional_funding)}
    scenarios = []
    for label, rent_factor, rate_add, void_add, cost_factor in [
        ("Base", 1, 0, 0, 1), ("Lower rent", 1-a["rent_stress_pct"]/100, 0, 0, 1),
        ("Higher interest", 1, a["rate_stress_pp"], 0, 1), ("Higher operating costs", 1, 0, 0, 1+a["cost_stress_pct"]/100),
        ("More vacancy (+5pp)", 1, 0, 5, 1),
        ("Combined downside", 1-a["rent_stress_pct"]/100, a["rate_stress_pp"], 5, 1+a["cost_stress_pct"]/100)]:
        sa = dict(stable_a, interest_rate_pct=a["interest_rate_pct"]+rate_add, void_pct=min(100, a["void_pct"]+void_add))
        for k in ("management_pct", "maintenance_pct", "insurance", "compliance", "letting_fees", "other_annual_costs", "void_cost_monthly", "service_charge", "ground_rent"):
            sa[k] = (sa[k] or 0) * cost_factor
        sr, _, _ = project(sa, price, rent * rent_factor)
        scenarios.append({"name": label, "monthly_rent": money(rent*rent_factor), "interest_rate_pct": sa["interest_rate_pct"] if loan else None,
                          "void_pct": sa["void_pct"], "monthly_cashflow": money(sum(r["cashflow_before_tax"] for r in sr)/12)})
    denom = (1-a["void_pct"]/100)*(1-a["management_pct"]/100)-a["maintenance_pct"]/100
    fixed = stable[0]["fixed_costs"] + stable[0]["void_costs"]
    metrics["break_even_rent"] = money((fixed+debt)/denom) if denom > 0 else None
    tests = [
        {"label": "Net yield on total cost", "target": a["min_net_yield_pct"], "actual": net_yield, "unit": "%", "passes": stable_noi / project_cost * 100 >= a["min_net_yield_pct"]},
        {"label": "Monthly cash flow before income tax", "target": a["min_monthly_cashflow"], "actual": metrics["monthly_cashflow_before_tax"], "unit": "GBP", "passes": stable_cash / 12 >= a["min_monthly_cashflow"]}]
    if i["cash_budget"] is not None:
        tests.append({"label": "Cash needed within investor budget", "target": i["cash_budget"], "actual": money(cash_required+additional_funding), "unit": "GBP", "passes": cash_required+additional_funding <= i["cash_budget"]})
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
    if p["property_type"] == "flat" and p["cladding_status"] in ("unknown", "concern"):
        flag("critical", "Building safety needs review", "Obtain applicable fire safety / cladding evidence and confirm lender requirements.")
    if p["epc_rating"] == "unknown":
        flag("warning", "EPC not confirmed", "Confirm the certificate, floor area and any improvement works required for letting.")
    elif p["epc_rating"] in ("F", "G"):
        flag("critical", "Low EPC rating", "Confirm current letting eligibility, exemptions and improvement costs before proceeding.")
    if not a["rent_source"] and not rental_comps:
        flag("warning", "Selected rent has no property-specific evidence", "Add an agent opinion or matched comparables; an asking rent is not proof of achieved rent.")
    if len(rental_comps) < 3:
        flag("warning", "Limited matched rental evidence", "Fewer than three rental comparables have been selected by the analyst.")
    if len(sold_comps) < 3:
        flag("warning", "Limited matched sold evidence", "Fewer than three sold transactions selected; an area average does not establish this property's value.")
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
        flag("warning", "Mortgage terms are assumptions", "Replace the illustrative rate and fees with a broker quote; rates are held constant through the projection.")
    if not a["cost_source"]:
        flag("warning", "Running costs need confirmation", "Default budgets are illustrative. Confirm charges, insurance, management and repair costs.")
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
    passes = all(t["passes"] for t in tests)
    verdict = "Meets configured financial targets" if passes else "Below one or more financial targets"
    if any(f["level"] == "critical" for f in flags):
        verdict = "Provisional — material evidence gaps" if mode != "demo" else "DEMO — fictional example"
    return {"available": True, "metrics": metrics, "rent_basis": rent_basis, "effective_assumptions": a,
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
                "Repayment debt includes interest and principal; interest-only principal is repaid at exit. Rates are assumed constant. No refinance, rent uplift from refurbishment or automatic house-price growth is assumed.",
                "All costs are cash budgets including VAT where supplied. Maintenance / major works allowances are treated as spent. The separate initial cash buffer is returned at exit, with deficits funded from that buffer first.",
                "Targets and cost defaults are editable screening assumptions, not industry standards. Sold comparison uses selected unadjusted transaction prices and requires an analyst to assess size, age, condition and location.",
                "Income and sale taxes use optional adviser-supplied amounts only. Annual IRR assumes year-end cash flows and is unavailable for ambiguous cash-flow patterns. Projections and stress scenarios are assumptions, not forecasts."
            ]}
