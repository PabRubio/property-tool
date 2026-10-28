"""Ownership-specific explanation; does not infer a client's personal tax bill."""

REFERENCES = [
    {'id':'ownership-tax','title':'HMRC — tax on rental income and allowable expenses','url':'https://www.gov.uk/renting-out-a-property/paying-tax','status':'reference'},
    {'id':'disposal-tax','title':'HMRC — tax when selling property','url':'https://www.gov.uk/tax-sell-property','status':'reference'},
    {'id':'company-disposal-tax','title':'HMRC — Corporation Tax on chargeable gains','url':'https://www.gov.uk/tax-when-your-company-sells-assets','status':'reference'},
    {'id':'finance-tax-relief','title':'HMRC — residential landlord finance-cost relief','url':'https://www.gov.uk/guidance/changes-to-tax-relief-for-residential-landlords-how-its-worked-out-including-case-studies','status':'reference'}]


def tax_summary(model):
    a=model['effective_assumptions']
    if a['buyer_type']=='company':
        text='Company ownership: rental profits and taxable gains on sale fall within Corporation Tax. Property-loan interest can generally be an allowable expense, subject to the company rules. Taking money out of the company may create a separate personal tax charge; this is not modelled. [ownership-tax, company-disposal-tax]'
    else:
        text='Individual ownership: rental profit is subject to Income Tax. Residential finance costs generally receive a basic-rate tax reduction, subject to limits, rather than a full deduction from rental income. Capital Gains Tax may apply on sale. The investor’s income, allowances and reliefs affect the actual bill. [ownership-tax, finance-tax-relief, disposal-tax]'
    text+= ' Purchase SDLT follows the stated buyer details; it cannot be calculated without a purchase price. ' if model.get('sdlt',{}).get('total') is None and model.get('available') is False else ' Purchase SDLT is included using the stated buyer details. '
    text+='Annual income tax is excluded. ' if a['annual_tax_budget'] is None else 'The supplied annual tax budget is deducted in the after-budget projection. '
    text+='Disposal tax is excluded. ' if a['sale_tax_budget'] is None else 'The supplied disposal-tax budget is deducted on sale. '
    text+='Refurbishment cash spend is not automatically a deductible repair expense. This is an indicative explanation, not a calculated tax return.'
    return text
