"""Auditable decision inputs for the writer. AI explains these, not calculates them."""
from .finance import stamp_duty, project, money


def operating_costs(inputs, model):
    a = model['effective_assumptions']; rent = model['metrics']['monthly_rent']
    provenance = inputs.get('input_provenance', {})
    rows = []
    def add(key, label, annual, includes):
        supplied = a.get(key) is not None
        rows.append({'key': key, 'label': label, 'annual': money(annual) if supplied else None,
                     'monthly': money(annual/12) if supplied else None, 'includes': includes,
                     'basis': provenance.get('assumptions.'+key, {}).get('basis', 'Unconfirmed modelling budget') if supplied else 'Unknown; excluded, not assumed free',
                     'source_ids': ['assumptions']})
    add('management_pct', 'Letting management', rent*12*(1-a['void_pct']/100)*a['management_pct']/100, '%s%% of collected rent; routine agent management, not letting/renewal charges.' % a['management_pct'])
    add('maintenance_pct', 'Repairs and maintenance', rent*12*a['maintenance_pct']/100, '%s%% of scheduled rent for routine repairs and small replacements. Excludes cleaning, planned refurbishment and separately budgeted major works.' % a['maintenance_pct'])
    for key, label, description in [
        ('regular_cleaning', 'Regular cleaning', 'Landlord-paid recurring cleaning, e.g. shared areas. Confirm frequency, areas, VAT and who pays; no automatic tenant cleaning charge.'),
        ('turnover_cleaning', 'Cleaning between tenancies', 'Annual landlord-paid changeover cleaning budget; confirm cost per clean and expected tenancy changes. Excludes routine cleaning.'),
        ('service_charge', 'Service / estate charge', 'Building or estate costs. Check the schedule for cleaning or repairs already covered; avoid double counting.'),
        ('ground_rent', 'Ground rent', 'Lease ground rent, where applicable.'),
        ('insurance', 'Landlord insurance', 'Illustrative annual premium; cover, excesses and flood exclusions require a quote.'),
        ('compliance', 'Safety and compliance', 'Annual budget for inspections/certificates; not proof that legal requirements have been met.'),
        ('letting_fees', 'Letting / renewal fees', 'Landlord-paid tenant finding or renewals; separate from recurring management.'),
        ('other_annual_costs', 'Other costs / major works', 'Only the stated budget; no survey-based major works forecast is implied.')]:
        add(key, label, a.get(key) or 0, description)
    add('void_cost_monthly', 'Empty-period bills', a['void_cost_monthly']*12*a['void_pct']/100, '£%s per fully empty month, weighted by %s%% ongoing vacancy. Council tax/utilities; lost rent is separate. Initial empty months affect the first-year schedule.' % (a['void_cost_monthly'], a['void_pct']))
    return rows


def purchase_guidance(inputs, model):
    a = model['effective_assumptions']; rent = model['metrics']['monthly_rent']
    noi = model['metrics']['stabilised_noi']
    fixed_loan = a.get('mortgage_amount') if a['financing'] != 'cash' else None
    budget = inputs['investor'].get('cash_budget')
    def at(price):
        cost = price + stamp_duty(price, a)['total'] + a['legal_fees'] + a['survey_fees'] + a['other_purchase_costs'] + model['metrics']['refurbishment_with_contingency']
        stable, loan, _ = project(dict(a, holding_years=1, initial_void_months=0), price, rent)
        monthly = sum(r['cashflow_before_tax'] for r in stable)/12
        cash = cost - loan + a['mortgage_fees'] + a['cash_reserve']
        rows, _, _ = project(a, price, rent)
        funding = max(0, -min(0, min(r['cumulative_cashflow'] for r in rows))-a['cash_reserve'])
        return {'yield': noi/cost*100, 'cashflow': monthly, 'cash': cash+funding}
    def ceiling(test, low=1):
        high = 100000000
        if not test(at(low)): return None
        if test(at(high)): return None  # No finite ceiling within the supported price range.
        for _ in range(45):
            mid = (low+high)/2
            if test(at(mid)): low = mid
            else: high = mid
        # Round down to avoid recommending a price that fails at the penny boundary.
        return int(low*100)/100
    target = a['min_net_yield_pct']
    yield_cap = ceiling(lambda r:r['yield'] >= target) if target > 0 else None
    low = max(1, (fixed_loan or a.get('deposit_amount') or 0)+.01)
    def passes(r):
        return r['yield'] >= target and r['cashflow'] >= a['min_monthly_cashflow'] and (budget is None or r['cash'] <= budget)
    feasible = passes(at(low))
    cap = ceiling(passes, low) if feasible else None
    market = model['sales_evidence']['range']
    overlap = [market[0], min(market[1], cap)] if market and cap and cap >= market[0] else None
    return {'yield_price_ceiling': yield_cap, 'all_targets_price_ceiling': cap,
            'feasible_with_current_finance': feasible, 'supported_purchase_range': market,
            'range_meeting_targets': overlap, 'recommended_bid_ceiling': overlap[1] if overlap else None,
            'finance_basis': 'Supplied mortgage amount stays fixed; a purchase price must exceed that loan.' if fixed_loan is not None else ('Cash purchase.' if a['financing'] == 'cash' else ('Supplied cash deposit stays fixed; borrowing changes with the purchase price.' if a.get('deposit_amount') is not None else 'Mortgage amount varies with the supplied deposit percentage / LTV.')),
            'method': 'Price ceiling solves the configured net-yield, monthly pre-tax cash-flow and available-cash tests, recalculating SDLT and acquisition costs. Cash includes reserves and projected additional funding. It is a return-based ceiling, not market value or a lender offer.',
            'limitations': 'Comparable range is unadjusted completed-sale evidence; condition, legal title and size conflicts require review. Unknown costs are excluded. No arbitrary auction discount or guaranteed winning bid is assumed.',
            'reason': 'No price satisfies every configured target with the current financing.' if not feasible else ('A supported bid range requires both sufficiently matched sales and a finite return-based ceiling.' if not overlap else 'Intersection of the supported sales range and the return-based ceiling.'),
            'target_basis': {key: inputs.get('input_provenance', {}).get('assumptions.'+key, {}).get('basis', 'Configured screening assumption') for key in ('min_net_yield_pct', 'min_monthly_cashflow')}}
