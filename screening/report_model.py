"""Render missing financial results in the normal report without inventing values."""
from .schema import defaults
from .evidence import enriched_inputs, local_growth, valuation
from .comparisons import comparison_summary
from .market_evidence import property_context, sample_context, demand_context, regional_rent_growth, growth_check, annualised
from .assumptions import apply_cost_policy, assumption_register
from .finance import money, borrowing, payment, stamp_duty, monthly_operations, TAX
from .providers import now


def prepare_unavailable(record):
    """Keep evidence and inputs; every uncomputed result is None, never zero."""
    original = record.get('analysis') or {}
    inputs = enriched_inputs(record['inputs'], record['evidence'])
    a = {**defaults()['assumptions'], **inputs['assumptions']}
    inputs['assumptions'] = a
    e = record['evidence']; p = inputs['property']
    policy = apply_cost_policy(inputs, e)
    sold = comparison_summary(inputs, e, 'sold'); rent = comparison_summary(inputs, e, 'rent')
    price = a.get('purchase_price') or p.get('asking_price')
    resolved=original.get('resolved_inputs') or {}
    monthly_rent = a.get('monthly_rent') if a.get('monthly_rent') is not None else resolved.get('monthly_rent')
    rent_growth=regional_rent_growth(e)
    rent_growth_basis='Supplied rent-growth scenario; not a forecast'
    if a.get('rent_growth_pct') is None:
        a['rent_growth_pct']=rent_growth['rate'] if rent_growth['rate'] is not None else 0
        rent_growth_basis=rent_growth['reason']
    price_growth_basis='Supplied price-growth scenario; not a forecast'
    if a.get('price_growth_pct') is None:
        a['price_growth_pct']=0
        price_growth_basis='No growth assumed: insufficient local history to estimate a trend'
        for source,series in [('growth',local_growth(e)),('growth-psf',growth_check(e)['psf_series'])]:
            rate=annualised(series)
            if rate is not None:
                a['price_growth_pct']=rate
                price_growth_basis='Scenario extends the annualised local trend, '+series[0]['month']+' to '+series[-1]['month']+' ['+source+']; not a forecast'
                break
    missing = list(original.get('missing') or [])
    if price is None and 'purchase_price' not in missing: missing.append('purchase_price')
    if monthly_rent is None and 'monthly_rent' not in missing: missing.append('monthly_rent')
    labels = {'purchase_price':'purchase price', 'monthly_rent':'monthly rent', 'financing':'financing choice'}
    reason = 'Awaiting '+', '.join(labels.get(k, k.replace('_',' ')) for k in missing)+'.'
    sdlt = stamp_duty(price,a) if price is not None else {'total':None,'basis':'Purchase price not established','rules':TAX}
    works = money(a['refurbishment']*(1+a['contingency_pct']/100)) if a.get('refurbishment') is not None else None
    loan = borrowing(a,price) if price is not None and a['financing'] not in ('unknown','mortgage_unsure') else None
    debt = payment(loan,a['interest_rate_pct'],a['mortgage_term_years']*12,a['financing']) if loan is not None else None
    acquisition = None if sdlt['total'] is None else sdlt['total']+a['legal_fees']+a['survey_fees']+a['other_purchase_costs']+(a.get('fire_safety_upfront') or 0)
    total = price+acquisition+works if price is not None and acquisition is not None and works is not None else None
    cash = total-loan+a['mortgage_fees']+a['cash_reserve'] if total is not None and loan is not None else None
    metrics = {k:None for k in ('gross_yield_pct','net_yield_on_cost_pct','cash_on_cash_pct','stabilised_noi',
               'monthly_cashflow_before_tax','additional_cash_needed','dscr','purchase_price_per_sqft')}
    metrics.update(purchase_price=price,monthly_rent=monthly_rent,loan=loan,monthly_debt_payment=debt,
                   cash_required=cash,total_property_cost=total,acquisition_costs=acquisition,
                   refurbishment_with_contingency=works,
                   floor_area_sqft=money(p['floor_area_sqm']*10.7639104167) if p.get('floor_area_sqm') else None)
    fields = ('scheduled_rent','lost_rent','collected_rent','management','maintenance','fixed_costs','void_costs',
              'operating_costs','net_operating_income','interest','principal','debt_payment','cashflow_before_tax',
              'tax_budget','cashflow','loan_balance','cumulative_cashflow','interest_rate_pct','regular_cleaning','turnover_cleaning')
    def schedule(years):
        rows=[]
        for i in range(years*12):
            row=dict(dict.fromkeys(fields),month=i+1,year=i//12+1)
            if monthly_rent is not None:row.update({k:money(v) for k,v in monthly_operations(a,monthly_rent,i).items()})
            rows.append(row)
        return rows
    horizons = [{'years':years,'available':False,'monthly':schedule(years),'annual':[]} for years in sorted({3,5,10,a['holding_years']})]
    guide = {k:None for k in ('supported_purchase_range','yield_price_ceiling','all_targets_price_ceiling',
                             'funding_price_ceiling','range_meeting_targets','recommended_bid_ceiling')}
    guide.update(reason='A bid is not established by the available inputs and evidence.',finance_basis='Financing uses the supplied choices.',
                 target_basis={k:inputs.get('input_provenance',{}).get('assumptions.'+k,{}).get('basis','Configured screening assumption') for k in ('min_net_yield_pct','min_monthly_cashflow')})
    scenarios = []
    for name, rent_change, rate_change, cost_change, void in [
        ('Base',0,0,0,a['void_pct']),('Lower rent',-a['rent_stress_pct'],0,0,a['void_pct']),
        ('Higher interest',0,a['rate_stress_pp'],0,a['void_pct']),('Higher operating costs',0,0,a['cost_stress_pct'],a['void_pct']),
        ('90% occupancy',0,0,0,10),('Combined downside',-a['rent_stress_pct'],a['rate_stress_pp'],a['cost_stress_pct'],a['void_pct']+5)]:
        scenarios.append(dict(name=name,rent_change_pct=rent_change,rate_change_pp=rate_change,cost_change_pct=cost_change,
                              monthly_rent=money(monthly_rent*(1+rent_change/100)) if monthly_rent is not None else None,
                              interest_rate_pct=a['interest_rate_pct']+rate_change,void_pct=void,monthly_cashflow=None))
    model = dict(original, available=False,version=5,missing=missing,unavailable_reason=reason,metrics=metrics,
        effective_assumptions=a,effective_property=p,cost_policy=policy,assumption_register=assumption_register(inputs,a),
        sdlt=sdlt,verdict='Financial results pending',purchase_guidance=guide,valuations={'sale':valuation(e,'sale'),'rent':valuation(e,'rent')},
        sales_evidence=sold,rental_evidence=rent,local_growth=local_growth(e),property_context=property_context(inputs,e),
        market_context={'rent_sample':sample_context(e,'rents'),'sales_demand':demand_context(e,'demand'),'rental_demand':demand_context(e,'demand-rent')},
        price_basis='Supplied price' if price is not None else 'No purchase price established',
        rent_basis='Supplied rent assumption' if a.get('monthly_rent') is not None else resolved.get('rent_basis','No rent selected for the financial model'),
        price_growth_basis=price_growth_basis,rent_growth_basis=rent_growth_basis,
        starting_value=None,value_basis='No starting market value established',
        funding={'cash_available':inputs['investor'].get('cash_budget'),'cash_required':cash,'extra_cash_needed':None},
        refurbishment_reference={'included':a['refurbishment_planned'],'requested':a['refurb_level']!='none','estimate':a['refurbishment'],
                                 'basis':'Supplied works budget','cost_basis':'Contingency is separate'},
        refurbishment_uplift={'included':a['refurbishment_planned'],'amount':None,'completion_month':a['initial_void_months'],
                             'basis':'After-works value has not been calculated','source_ids':['assumptions'],
                             'no_uplift_sale_price':None,'no_uplift_total_profit':None},
        monthly=schedule(a['holding_years']),annual=[dict(dict.fromkeys(('collected_rent','operating_costs','interest','principal','cashflow_before_tax')),year=y) for y in range(1,11)],
        scenarios=scenarios,horizons=horizons,rate_comparisons=[],interest_coverage={'base_pct':None,'stress_pct':None,'stress_rate_pct':None},
        tests=[{'label':'Net yield on total cost','target':a['min_net_yield_pct'],'actual':None,'unit':'%','passes':None},
               {'label':'Monthly cash flow before income tax','target':a['min_monthly_cashflow'],'actual':None,'unit':'GBP','passes':None}])
    from .decision import operating_costs
    model['operating_costs']=operating_costs(inputs,model)
    if monthly_rent is not None:
        stable=dict(a,initial_void_months=0)
        metrics['stabilised_noi']=money(sum(monthly_operations(stable,monthly_rent,i)['net_operating_income'] for i in range(12)))
        annual_schedule=schedule(10)
        for row in model['annual']:
            months=annual_schedule[(row['year']-1)*12:row['year']*12]
            for field in ('collected_rent','operating_costs'):row[field]=money(sum(m[field] for m in months))
        if a['financing'] not in ('unknown','mortgage_unsure') and works is not None:
            from .decision import purchase_guidance
            model['purchase_guidance']=purchase_guidance(inputs,model)
    record['analysis']=model
    previous=(record.get('narrative') or {}).get('content',{})
    # Keep investigative prose and prior next steps in the internal document.
    internal=list(previous.get('due_diligence') or previous.get('next_steps') or [])
    if previous.get('summary') and previous['summary'] not in internal:internal.append(previous['summary'])
    def item(text):return {'text':text,'source_ids':['inputs','assumptions','model']}
    record['narrative']={'provider':'saved_evidence','model':'deterministic','generated_at':now(),'content':{
        'summary':item('The property facts, market evidence and supplied budgets are set out below. Financial returns and a bid recommendation are not yet calculated. '+reason),
        'purchase_conclusion':item('The supplied cash budget and financing terms are shown separately from market evidence. No purchase price or bid is implied by an unavailable result.'),
        'rent_conclusion':item('Advertised rents below are comparison evidence. Differences in bedroom count, property size and letting terms remain relevant to an achievable rent.'),
        'growth_conclusion':item('Historical area prices provide context. Future values and investment returns are not calculated until the necessary financial inputs are established.'),
        'stress_conclusion':item('The scenario settings are shown, but their cash-flow effects are not calculated while essential inputs remain unavailable.'),
        'strengths':[],'risks':[item('Financial targets have not been assessed. An unavailable result is neither a pass nor a fail.'),
                               item('Financing terms are supplied assumptions, not a lender offer. Income and disposal taxes depend on the ownership structure and individual circumstances.'),
                               item('HMO or other licensing obligations depend on the actual letting arrangements. An unresolved flood or listed-building status is not a clearance.')],
        'due_diligence':internal}}
    return model
