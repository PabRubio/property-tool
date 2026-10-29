"""Keep independent calculations when a core modelling input is unavailable."""
from .finance import stamp_duty, borrowing, payment, project, ratio, money, refurbishment_estimate
from .comparisons import comparison_summary
from .evidence import valuation, local_growth
from .market_evidence import property_context, sample_context, demand_context, growth_check, regional_rent_growth, annualised
from .modelling import works_value


def partial_analysis(inputs, evidence, a, basis, strategy, price, rent, price_basis, rent_basis, missing):
    a = dict(a, purchase_price=price, monthly_rent=rent)
    p = inputs['property']
    history=local_growth(evidence);crosscheck=growth_check(evidence);regional=regional_rent_growth(evidence)
    price_growth_basis='Supplied price-growth scenario; not a forecast'
    rent_growth_basis='Supplied rent-growth scenario; not a forecast'
    def unset(key):return a[key] is None or a[key]==0 and basis[key].startswith('Illustrative default')
    if unset('price_growth_pct'):
        a['price_growth_pct']=0;price_growth_basis='No growth assumed: insufficient local history'
        for source,series in [('growth',history),('growth-psf',crosscheck['psf_series'])]:
            rate=annualised(series)
            if rate is not None:
                a['price_growth_pct']=rate;price_growth_basis='Scenario extends annualised local history, '+series[0]['month']+' to '+series[-1]['month']+' ['+source+']; not a forecast'
                break
    if unset('rent_growth_pct'):
        a['rent_growth_pct']=regional['rate'] if regional['rate'] is not None else 0;rent_growth_basis=regional['reason']
    if a['financing'] == 'cash': a['mortgage_fees'] = 0
    works = 0 if a['refurb_level']=='none' else a['refurbishment'] if a['refurbishment'] is not None else refurbishment_estimate(evidence)
    a['refurbishment'] = works
    refurb = works*(1+a['contingency_pct']/100) if works is not None else None
    sdlt = stamp_duty(price,a) if price is not None else {'total':None,'basis':'Purchase price unavailable','rules':{},'bands':[]}
    acquisition = sdlt['total']+a['legal_fees']+a['survey_fees']+a['other_purchase_costs']+a['safety_upfront'] if price is not None else None
    cost = price+acquisition+refurb if price is not None and refurb is not None else None
    loan = None
    if a['financing']=='cash': loan=0
    elif 'financing' not in missing and 'mortgage_amount' not in missing:
        loan = borrowing(a,price) if price is not None else a.get('mortgage_amount')
    debt = payment(loan,a['interest_rate_pct'],a['mortgage_term_years']*12,a['financing']) if loan is not None else None
    cash = cost-loan+a['mortgage_fees']+a['cash_reserve'] if cost is not None and loan is not None else None
    noi = None
    if rent is not None:
        # Operating income does not depend on purchase price or borrowing.
        rows,_,_ = project(dict(a,financing='cash',holding_years=1,initial_void_months=0),0,rent)
        noi = sum(row['net_operating_income'] for row in rows)
    flow = noi/12-debt if noi is not None and debt is not None else None
    area = p.get('floor_area_sqm')
    v = dict(purchase_price=price,monthly_rent=rent,gross_yield_pct=ratio(rent*12,price) if rent is not None and price else None,
             floor_area_sqft=money(area*10.7639104167) if area else None,
             purchase_price_per_sqft=money(price/(area*10.7639104167)) if price and area else None,
             total_property_cost=money(cost) if cost is not None else None,acquisition_costs=money(acquisition) if acquisition is not None else None,
             loan=money(loan) if loan is not None else None,monthly_debt_payment=money(debt) if debt is not None else None,
             refurbishment_with_contingency=money(refurb) if refurb is not None else None,cash_required=money(cash) if cash is not None else None,
             stabilised_noi=money(noi) if noi is not None else None,monthly_cashflow_before_tax=money(flow) if flow is not None else None,
             net_yield_on_cost_pct=ratio(noi,cost) if noi is not None and cost else None,
             cash_on_cash_pct=ratio(flow*12,cash) if flow is not None and cash else None,additional_cash_needed=None,
             monthly_cashflow_after_tax_budget=None,break_even_rent=None,dscr=None)
    sales=comparison_summary(inputs,evidence,'sold'); rental=comparison_summary(inputs,evidence,'rent')
    current=valuation(evidence,'sale') or price
    context=property_context(inputs,evidence)
    model={'version':5,'available':False,'missing':missing,'metrics':v,'effective_assumptions':a,'effective_property':p,
           'modelling_basis':basis,'letting_strategy':strategy,'rent_basis':rent_basis if rent is not None else 'Rent unavailable',
           'price_basis':price_basis,'starting_value':current,'value_basis':'Sale valuation or supplied purchase-price proxy',
           'refurbishment_value':works_value(a,current,evidence),'price_growth_basis':price_growth_basis,
           'rent_growth_basis':rent_growth_basis,'local_growth':history,
           'growth_crosscheck':crosscheck,'regional_rent_growth':regional,'property_context':context,
           'rental_evidence':rental,'sales_evidence':sales,'valuations':{'sale':valuation(evidence,'sale'),'rent':valuation(evidence,'rent')},
           'market_context':{'rent_sample':sample_context(evidence,'rents'),'sales_demand':demand_context(evidence,'demand'),
                             'rental_demand':demand_context(evidence,'demand-rent')},
           'sdlt':sdlt,'refurbishment_reference':{'estimate':refurbishment_estimate(evidence),'requested':a['refurb_level']!='none',
                'included':a['refurb_level']!='none','basis':'Saved works estimate / supplied budget','cost_basis':'Unavailable' if works is None else 'Budget; unverified'},
           'flags':context['flags']+[{'level':'critical','title':'Financial assessment incomplete','detail':'Unavailable inputs: '+', '.join(missing)+'. Dependent results are unavailable.'}],
           'verdict':'Financial assessment incomplete — essential inputs unavailable','monthly':[],'annual':[],'scenarios':[],
           'horizons':[],
           'funding':{'cash_required':v['cash_required'],'cash_available':inputs['investor']['cash_budget'],'additional_cash_needed':None,
                       'initial_shortfall':money(max(0,cash-inputs['investor']['cash_budget'])) if cash is not None and inputs['investor']['cash_budget'] is not None else None,
                       'shortfall':None},
           'rate_comparisons':[],'interest_coverage':{'base_pct':None,'stress_pct':None,'stress_rate_pct':a['interest_rate_pct']+a['rate_stress_pp']},
           'purchase_guidance':{'supported_purchase_range':sales['range'],'yield_price_ceiling':None,'all_targets_price_ceiling':None,'range_meeting_targets':None,
               'finance_basis':'Borrowing as supplied; missing terms remain unavailable.','reason':'Price ceilings require complete inputs.',
               'target_basis':{k:basis[k] for k in ('min_net_yield_pct','min_monthly_cashflow')}}}
    model['tests']=[{'label':label,'target':a[key],'actual':actual,'unit':unit,'passes':actual>=a[key] if actual is not None else None}
                    for label,key,actual,unit in [('Net yield on total cost','min_net_yield_pct',v['net_yield_on_cost_pct'],'%'),
                      ('Monthly cash flow before income tax','min_monthly_cashflow',v['monthly_cashflow_before_tax'],'GBP')]]
    from .decision import operating_costs
    costs=operating_costs(inputs,dict(model,metrics=dict(v,monthly_rent=rent or 0)))
    if rent is None:
        for row in costs:
            if row['key'] in ('management_pct','maintenance_pct'): row.update(annual=None,monthly=None,basis='Unavailable until rent supplied')
    model['operating_costs']=costs
    for years in sorted({3,5,10,a['holding_years']}):
        value=model['refurbishment_value']['after_works_value']
        future=money(value*(1+a['price_growth_pct']/100)**years) if value is not None else None
        proceeds=None
        within_term=a['financing']!='interest_only' or years<=a['mortgage_term_years']
        if loan is not None and within_term and future is not None:
            # Only read the debt balance: debt amortisation is independent of rent.
            debt_rows,_,_=project(dict(a,holding_years=years),price or 0,0)
            proceeds=money(future*(1-a['selling_fee_pct']/100)-a['sale_legal_fees']-a['early_repayment_fee']-debt_rows[-1]['loan_balance']-(a['sale_tax_budget'] or 0))
        rental_income=None
        if rent is not None:
            rent_rows,_,_=project(dict(a,financing='cash',holding_years=years),0,rent)
            rental_income=money(sum(row['collected_rent'] for row in rent_rows))
        model['horizons'].append({'years':years,'available':False,'reason':'Incomplete inputs: '+', '.join(missing),
                                 'rental_income':rental_income,'rental_cashflow':None,
                                 'exit':{'sale_price':future,'sale_proceeds':proceeds,'annual_irr_pct':None,'total_profit':None}})
    return model
