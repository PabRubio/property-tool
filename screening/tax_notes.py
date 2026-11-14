"""Dated government references for explanation, separate from the SDLT engine."""
VERIFIED_ON = '2026-10-29'
REFERENCES = [
    ('tax-income','HMRC — rental income and allowable expenses','https://www.gov.uk/renting-out-a-property/paying-tax'),
    ('tax-finance','HMRC — residential landlord finance-cost relief','https://www.gov.uk/guidance/changes-to-tax-relief-for-residential-landlords-how-its-worked-out-including-case-studies'),
    ('tax-company','HMRC — Corporation Tax rates','https://www.gov.uk/corporation-tax-rates'),
    ('tax-disposal','HMRC — tax when selling property','https://www.gov.uk/tax-sell-property'),
    ('tax-ated','HMRC — Annual Tax on Enveloped Dwellings','https://www.gov.uk/guidance/annual-tax-on-enveloped-dwellings-the-basics'),
    ('safety-gov','GOV.UK — landlord safety responsibilities','https://www.gov.uk/renting-out-a-property/landlord-responsibilities')]


COMMERCIAL_VERIFIED_ON = '2026-11-12'
COMMERCIAL_REFERENCES = [ref for ref in REFERENCES if ref[0] in ('tax-income','tax-company','tax-disposal')] + [
    ('tax-nonresidential','HMRC — non-residential SDLT','https://www.gov.uk/stamp-duty-land-tax/nonresidential-and-mixed-rates'),
    ('tax-vat','HMRC — land and property VAT Notice 742','https://www.gov.uk/guidance/vat-on-land-and-property-notice-742'),
    ('tax-rates','GOV.UK — empty-property business rates relief','https://www.gov.uk/business-rates-relief/empty-property-relief')]


def tax_explanation(a):
    if a.get('_asset_class') == 'commercial':
        ownership = ('Company rental profits and chargeable gains normally fall within Corporation Tax. [tax-company, tax-disposal] '
                     if a['buyer_type'] == 'company' else
                     'Individual rental profits are subject to Income Tax after allowable expenses; disposal gains may attract Capital Gains Tax. [tax-income, tax-disposal] ')
        return (ownership + 'England non-residential SDLT includes charged purchase VAT in consideration; new-lease or complex tax requires adviser confirmation and an override. [tax-nonresidential] '
                'Full purchase VAT is funded at completion. Only the supplied recoverable share is credited in the specified month; net project cost excludes that recovery. Rent excludes pass-through VAT; costs include irrecoverable VAT. Confirm the option to tax and recovery eligibility. [tax-vat] '
                'Empty-property business rates use the supplied budget and relief months; eligibility is unverified. [tax-rates] '
                'Income tax / Corporation Tax and disposal tax are excluded unless separately budgeted; budgets are not tax assessments. Government commercial guidance checked '+COMMERCIAL_VERIFIED_ON+'.')

    if a['buyer_type']=='company':
        text=('Company ownership: rental profits and chargeable gains normally fall within Corporation Tax. The main rate is 25%; '
              'qualifying small profits may use 19% or marginal relief, subject to thresholds, associated companies and eligibility. '
              'Company finance costs follow corporation-tax rules, rather than the individual landlord restriction. [tax-company, tax-income, tax-finance, tax-disposal] '
              'ATED may apply to company-owned dwellings over £500,000; relief can still require a return. [tax-ated] '
              'Shareholder dividend/extraction taxes and ATED are excluded.')
    else:
        text=('Individual ownership: rental profits are subject to Income Tax after allowable expenses. Residential finance-cost relief '
              'is generally a basic-rate tax reduction subject to limits, not full mortgage-interest deduction; principal repayments are not expenses. '
              'A taxable gain on disposal may attract Capital Gains Tax. [tax-income, tax-finance, tax-disposal] '
              'National Insurance and inheritance tax are excluded.')
    text += (' SDLT is included in acquisition costs. Rental income / corporation tax '+
             ('is excluded' if a['annual_tax_budget'] is None else 'uses only the supplied annual tax budget')+
             '; disposal tax '+('is excluded' if a['sale_tax_budget'] is None else 'uses only the supplied sale-tax budget')+
             '. Headline cash flow is before income tax; budgets are not tax assessments. Government guidance checked '+VERIFIED_ON+'.')
    return text
