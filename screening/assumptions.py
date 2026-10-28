"""Explicit budget policies; research can replace defaults, never client choices."""
import re
from datetime import date


def letting_strategy(inputs):
    text = '\n'.join([inputs.get('analyst_notes',''), inputs.get('investor',{}).get('notes',''),
                      inputs.get('property',{}).get('listing_notes','')])
    for sentence in re.split(r'[.\n;]', text.lower()):
        if re.search(r'\b(no|not|potential|possible|possibly|could|might|consider|maybe)\b',sentence): continue
        if re.search(r'\b(hmo|student[ -](let|letting|house|rental|style)|let to students|room.by.room)\b',sentence):
            return 'hmo'
    return 'whole_house'


def apply_cost_policy(inputs, evidence):
    a = inputs['assumptions']; provenance = inputs.setdefault('input_provenance',{})
    strategy = letting_strategy(inputs)
    source = provenance.get('assumptions.management_pct',{}).get('basis','')
    default = source.startswith(('Illustrative default','Strategy default','Researched management')) or (not source and a.get('management_pct') in (12,14.4))
    basis = source or 'Supplied management budget; including VAT'
    refs = ['assumptions']
    if default:
        a['management_pct'] = 18 if strategy == 'hmo' else 14.4
        basis = ('Strategy default: 15% + VAT for an explicitly stated HMO / student letting' if strategy == 'hmo' else 'Strategy default: 12% + VAT for whole-house letting')+'; replace with an applicable agent quote'
        fact = evidence.get('researched_facts',{}).get('costs',{})
        quote = fact.get('value')
        if isinstance(quote,dict):
            rate = quote.get('management_pct')
            try: current = 0 <= (date.today()-date.fromisoformat(str(fact.get('evidence_date',''))[:10])).days <= 365
            except ValueError: current = False
            if (isinstance(rate,(int,float)) and not isinstance(rate,bool) and 0 <= rate <= 50 and
                quote.get('vat_included') is True and quote.get('applicable_strategy') == strategy and
                quote.get('local_provider') and quote.get('service_scope') == 'full_management' and current and fact.get('source_ids')):
                a['management_pct'] = rate
                basis = 'Researched management tariff including VAT: '+str(quote['local_provider'])+'; subject to property-specific quote'
                refs = fact['source_ids']
        provenance['assumptions.management_pct'] = {'basis':basis,'source_id':refs[0]}
    return {'strategy':strategy,'management_basis':basis,'source_ids':refs}


def assumption_register(inputs, effective):
    from .schema import FIELDS
    rows = []
    for key,label,group,default,_,_ in FIELDS:
        value = effective.get(key)
        source = inputs.get('input_provenance',{}).get('assumptions.'+key,{}).get('basis')
        if not source:
            source = 'Unspecified; excluded' if value is None else 'Default assumption' if value == default else 'Model input / derived value'
        rows.append({'key':key,'label':label,'value':value,'basis':source,'group':group})
    return rows
