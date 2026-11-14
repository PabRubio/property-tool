"""Single-unit commercial screening rules shared by intake, finance and reports."""
import copy

PROPERTY_TYPES = ('retail', 'offices', 'industrial')


def is_commercial(inputs):
    return inputs.get('property', {}).get('asset_class', 'residential') == 'commercial'


def area_basis(property_):
    return 'nia' if property_.get('property_type') == 'offices' else 'gia'


def valuation_area_ready(property_):
    return bool(property_.get('floor_area_sqm') and property_.get('floor_area_basis') == area_basis(property_))


def scoped_evidence(inputs, evidence):
    """Discard residential context, including imported legacy snapshots."""
    if not is_commercial(inputs): return evidence
    out = copy.deepcopy(evidence)
    residential = {'property', 'rents', 'prices', 'prices-per-sqf', 'sold-prices', 'sold-prices-per-sqf',
                   'valuation-sale', 'valuation-rent', 'growth', 'growth-psf', 'national-data', 'hpi',
                   'demand', 'demand-rent', 'build-cost', 'land-registry', 'land-registry-history'}
    out['asset_class'] = 'commercial'
    for group in ('raw', 'market'):
        for key in residential | {'monthly_rent'}: out.setdefault(group, {}).pop(key, None)
    out['profile'] = {}; out['hpi'] = []
    out['sources'] = [s for s in out.get('sources', []) if s.get('id') not in residential]
    out['comparables'] = [c for c in out.get('comparables', []) if c.get('property_type') in PROPERTY_TYPES]
    return out


def assumptions(inputs, a, basis):
    a['_asset_class'] = 'commercial'
    a['_occupancy'] = inputs['property'].get('occupancy', 'unknown')
    unpriced = []
    for key in ('management_pct', 'maintenance_pct', 'insurance', 'compliance', 'letting_fees',
                'safety_upfront', 'void_cost_monthly', 'legal_fees', 'survey_fees'):
        if a.get(key) is None or basis[key].startswith(('Illustrative default', 'Not supplied')):
            unpriced.append(key)
            a[key] = 0
            basis[key] = 'Unpriced commercial landlord cost; excluded, not assumed free'
    for key in ('business_rates_annual', 'service_charge', 'ground_rent', 'regular_cleaning', 'turnover_cleaning'):
        if a.get(key) is None: unpriced.append(key)
    a['_unpriced_commercial_costs'] = unpriced
    if a.get('maintenance_basis') == 'auto': a['maintenance_basis'] = 'rent'
    if a.get('safety_included_in') in ('refurbishment', 'other_purchase_costs'):
        a['safety_upfront'] = 0
        basis['safety_upfront'] = 'Included in ' + a['safety_included_in'].replace('_', ' ')
    a['rent_growth_pct'] = 0
    basis['rent_growth_pct'] = 'Commercial rent follows supplied lease review and reletting events; no annual residential rent inflation'
    if a.get('refurbishment_value_recovery_pct') == 50 and basis['refurbishment_value_recovery_pct'].startswith('Illustrative default'):
        a['refurbishment_value_recovery_pct'] = 0
        basis['refurbishment_value_recovery_pct'] = 'No automatic commercial value uplift from works'
    return a, basis, 'Single-unit commercial rental; landlord budgets and lease events as supplied'


def missing_terms(inputs, a):
    missing = []
    if a.get('purchase_vat_pct') is None: missing.append('purchase_vat_pct')
    if a.get('_occupancy') == 'unknown': missing.append('occupancy')
    if a.get('lease_remaining_months') is None: missing.append('lease_remaining_months')
    if a.get('_occupancy') == 'vacant' and inputs.get('input_provenance', {}).get('assumptions.initial_void_months', {}).get('basis', '').startswith('Illustrative default'):
        missing.append('initial_void_months')
    if a.get('new_lease') and a.get('sdlt_override') is None: missing.append('sdlt_override')
    return missing


def lease_month(a, rent, month):
    """Completion is month zero. Earliest break is exercised in this scenario."""
    start = a.get('initial_void_months', 0)
    term = a.get('lease_remaining_months')
    end = (start + term if a.get('_occupancy') == 'vacant' else term) if term is not None else None
    if a.get('break_month') is not None: end = min(end, a['break_month']) if end is not None else a['break_month']
    scheduled = rent
    review = a.get('rent_review_month')
    if review is not None and month >= review and a.get('rent_review_annual_rent') is not None:
        scheduled = a['rent_review_annual_rent'] / 12 * a.get('_rent_scenario_factor', 1)
    empty = month < start
    empty_age = month if empty else None
    if end is not None and month >= end:
        delay, relet = a.get('reletting_void_months'), a.get('reletting_annual_rent')
        empty = delay is None or relet is None or month < end + delay
        empty_age = month - end if empty else None
        if not empty: scheduled = relet / 12 * a.get('_rent_scenario_factor', 1)
    occupied = 0 if empty else 1 - a['void_pct'] / 100
    rent_free = not empty and start <= month < start + a.get('rent_free_months', 0)
    collected = 0 if rent_free else scheduled * occupied
    # Relief applies only to a discrete empty spell, never an average arrears allowance.
    rates_weight = (0 if empty_age < a.get('rates_relief_months', 0) else 1) if empty else 1 - occupied
    return scheduled, collected, occupied, rates_weight


def purchase_vat(price, a):
    return price * (a.get('purchase_vat_pct') or 0) / 100 if a.get('_asset_class') == 'commercial' else 0


def flags(inputs, a):
    result = []
    def add(title, detail, level='warning'): result.append({'level': level, 'title': title, 'detail': detail})
    if a.get('_unpriced_commercial_costs'):
        add('Commercial costs remain unpriced', 'Unpriced: ' + ', '.join(k.replace('_', ' ') for k in a['_unpriced_commercial_costs']) + '. Excluded from totals; landlord costs during vacancy and tenant recovery need confirmation.', 'critical')
    add('Commercial lease scenario', 'The earliest supplied break is assumed exercised. Rent stops at break or expiry unless an explicit reletting delay and rent are supplied. Reviews and rent-free periods follow supplied terms.')
    add('Commercial valuation limitations', 'Commercial estimates use quoted rents and standard capitalisation rates. They are screening references, not completed-sale evidence or valuations of the tenant covenant and lease.')
    if inputs['property'].get('rent_vat_status') == 'unknown':
        add('Rent VAT treatment unconfirmed', 'Rent is modelled excluding pass-through VAT. Confirm the option to tax and whether the supplied rent is VAT-exclusive.', 'critical')
    add('Commercial responsibilities need verification', 'Confirm permitted use, tenant covenant, repair and insurance obligations, recoverable service costs, non-domestic EPC and reletting costs against the actual lease.')
    add('Purchase VAT cash timing', 'All charged purchase VAT is funded at completion. Only the supplied recoverable share is repaid in the stated month; eligibility and timing require confirmation.')
    return result
