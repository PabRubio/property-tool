"""Cited cost estimates and explicit maintenance allowances; inputs stay unchanged."""
import hashlib
import json
import math
import re
from datetime import datetime, timezone

from .evidence import enriched_inputs
from .providers import now

KINDS = ('legal_fees', 'survey_fees', 'management_pct', 'maintenance_pct')
SCHEMA = {'type':'object', 'properties':{
    'kind':{'type':'string','enum':list(KINDS)}, 'estimate':{'type':'number'},
    'basis_type':{'type':'string','enum':['fee','collected_rent','scheduled_rent','property_value']},
    'basis':{'type':'string'}, 'limitations':{'type':'string'},
    'source_ids':{'type':'array','items':{'type':'string'}}, 'evidence_quote':{'type':'string'},
    'survey_level':{'type':'string','enum':['not_applicable','level_1','level_2','level_3']}},
    'required':['kind','estimate','basis_type','basis','limitations','source_ids','evidence_quote','survey_level'],
    'additionalProperties':False}

INSTRUCTIONS = '''Cost estimates: return cost_estimates for defaulted costs in cost_context. Use the SAME research rounds and time budget; no separate research loop. Prioritise missing purchase price/rent, then read relevant local fee schedules alongside other gaps. Supplied costs always win. Legal fees: one all-in purchase budget including VAT where charged, routine searches, registration and disbursements; exclude SDLT and the separate mortgage/product fees. Explain scope and adjustments. Survey fees: VAT-inclusive budget for the appropriate RICS survey level; identify level_1/level_2/level_3 and justify type/size/age/alterations. A lender valuation is not a condition survey. Use £2000 legal and £600 survey only as fallbacks when evidence is insufficient (omit that estimate). Management: percentage of COLLECTED rent inclusive of VAT, based on actual local comparable management services; exclude separate tenant-find/setup fees and explain package exclusions. Fee and management estimates require source_ids of actually scraped pages and an exact evidence_quote from a fee schedule, not search snippets. Do not confuse 'from' fees, rent guarantees, initial fees and recurring management. Maintenance: choose a percentage of annual scheduled rent for newer/leasehold flats or of property value for older/freehold houses; consider age, type, condition and tenure. Explain the actual facts used, the chosen percentage and the scope. A broad age band is not an exact age and high finish is not a survey. Avoid building repairs already included in service charges. Exclude cleaning, refurbishment and separately budgeted major works. This may be an analyst modelling allowance based on supplied facts: source_ids may then be empty and evidence_quote empty; never claim it is a quote or independently established repair liability. basis <=220 characters; limitations <=300. basis_type is fee for legal/survey, collected_rent for management, scheduled_rent or property_value for maintenance. survey_level is not_applicable except for survey fees. Report only estimates you can justify; keep the report usable with disclosed fallbacks when searches fail.'''


def fingerprint(inputs, evidence):
    inputs = enriched_inputs(inputs, evidence)
    p = inputs['property']
    fields = ('address','postcode','property_type','tenure','bedrooms','floor_area_sqm',
              'construction_date','finish_quality','new_build','asking_price')
    data = {'property':{k:p.get(k) for k in fields},
            'scope':{k:inputs['assumptions'].get(k) for k in ('purchase_price','monthly_rent','financing','buyer_type','refurb_level','service_charge','maintenance_basis','rent_source','cost_source')},
            'notes':[inputs.get('analyst_notes',''),inputs['investor'].get('notes',''),p.get('listing_notes','')]}
    return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()


def defaulted(inputs, key):
    basis = inputs.get('input_provenance',{}).get('assumptions.'+key,{}).get('basis','')
    return key not in inputs['assumptions'] or inputs['assumptions'][key] is None or basis.startswith('Illustrative default')


def apply(record, proposed, sources):
    observed = {s['id']:s for s in sources}
    accepted = {}
    for item in proposed if isinstance(proposed,list) else []:
        if not isinstance(item,dict) or item.get('kind') not in KINDS: continue
        kind=item['kind'];value=item.get('estimate');unit=item.get('basis_type')
        units = ['fee'] if kind in ('legal_fees','survey_fees') else ['collected_rent'] if kind=='management_pct' else ['scheduled_rent','property_value']
        ceiling = 5 if unit=='property_value' else 50 if kind.endswith('_pct') else 100000
        if unit not in units or isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0 < value <= ceiling: continue
        if any(not isinstance(item.get(k),str) or not 1 <= len(item[k].strip()) <= limit for k,limit in [('basis',220),('limitations',300)]): continue
        if item.get('survey_level') not in (('level_1','level_2','level_3') if kind=='survey_fees' else ('not_applicable',)): continue
        refs=item.get('source_ids',[])
        if not isinstance(refs,list) or any(not isinstance(x,str) or x not in observed for x in refs): continue
        if not isinstance(item.get('evidence_quote'),str):continue
        if not refs and kind!='maintenance_pct': continue
        if not refs and item['evidence_quote'].strip():continue
        if refs:
            normalize=lambda text:' '.join(str(text).replace('\\n',' ').split()).casefold()
            pieces=[normalize(x) for x in re.split(r'…|\.{3}',item.get('evidence_quote','')) if normalize(x)]
            def contains(source):
                page=normalize(' '.join(source.get('support',[])));cursor=0
                for piece in pieces:
                    position=page.find(piece,cursor)
                    if position<0:return False
                    cursor=position+len(piece)
                return True
            if sum(map(len,pieces))<20 or not any(contains(observed[x]) for x in refs):continue
        ids=[]
        for ref in refs:
            source=observed[ref];sid='research-'+hashlib.sha256(source['url'].encode()).hexdigest()[:10]
            if not any(s.get('id')==sid for s in record['evidence'].setdefault('sources',[])):
                record['evidence']['sources'].append(dict(source,id=sid,status='ok',retrieved_at=now(),scope='Published cost context; estimate scope and adjustments recorded separately'))
            ids.append(sid)
        accepted[kind]=dict(item,source_ids=ids,source_urls=refs,generated_at=now(),
                            fingerprint=fingerprint(record['inputs'],record['evidence']))
    record['evidence'].setdefault('cost_estimates',{}).update(accepted)
    return accepted


def current(inputs, evidence):
    result={};signature=fingerprint(inputs,evidence)
    refs={s['id'] for s in evidence.get('sources',[]) if s.get('status')=='ok'}
    for kind,item in evidence.get('cost_estimates',{}).items():
        try:age=(datetime.now(timezone.utc)-datetime.fromisoformat(item['generated_at'])).total_seconds()
        except (KeyError,ValueError,TypeError):continue
        if item.get('fingerprint')==signature and 0<=age<30*86400 and all(x in refs for x in item.get('source_ids',[])):
            result[kind]=item
    return result


def effective(inputs, evidence, a, basis, price, value):
    """Apply to the calculation copy only; preserve supplied figures and their meaning."""
    if a.get('_asset_class') == 'commercial':
        a['_maintenance_value'] = value if value is not None else price
        a['_cost_source_ids'] = {}
        return
    estimates=current(inputs,evidence);sources={}
    for kind in KINDS:
        if not defaulted(inputs,kind):continue
        item=estimates.get(kind)
        if item:
            requested=inputs['assumptions'].get('maintenance_basis','auto')
            selected='value' if item['basis_type']=='property_value' else 'rent'
            if kind=='maintenance_pct' and requested not in ('auto',selected):continue
            a[kind]=item['estimate'];sources[kind]=item['source_ids'] or ['inputs']
            scope=(' '+item['survey_level'].replace('_',' ').title()+'.') if kind=='survey_fees' else ''
            basis[kind]='Analyst estimate.'+scope+' '+item['basis']+' ['+', '.join(sources[kind])+']'
            if kind=='maintenance_pct':a['maintenance_basis']=selected
        elif kind in ('legal_fees','survey_fees'):
            a[kind]=2000 if kind=='legal_fees' else 600
            scope='VAT and routine searches/disbursements included; SDLT separate.' if kind=='legal_fees' else 'Survey scope unconfirmed; VAT-inclusive allowance.'
            basis[kind]='Fallback budget; no supported fee estimate. '+scope
    maintenance=inputs['assumptions'].get('maintenance_basis','auto')
    if not defaulted(inputs,'maintenance_pct'):
        a['maintenance_basis']='rent' if maintenance=='auto' else maintenance
    elif 'maintenance_pct' not in sources:
        p=enriched_inputs(inputs,evidence)['property'];flat=p['property_type'] in ('flat','converted_flat','studio')
        house_value=not flat and (p['tenure']=='freehold' or p.get('construction_date') in ('pre_1914','1914_2000'))
        use_value=maintenance=='value' or maintenance=='auto' and house_value and value is not None
        a['maintenance_basis']='value' if use_value else 'rent'
        a['maintenance_pct']=1 if use_value else 5
        basis['maintenance_pct']=('Fallback allowance: 1% of value; property-specific repairs unpriced, not a survey or quote.' if use_value else
                                  'Fallback allowance: 5% of scheduled rent; property-specific repairs unpriced.')
    a['_maintenance_value']=value if value is not None else price
    a['_cost_source_ids']=sources
    if a['maintenance_basis']=='value':
        reference=a['_maintenance_value']
        label='£{:,.0f}'.format(reference) if reference is not None else 'unavailable value'
        basis['maintenance_pct']+=' Basis: '+label+' initially; later years use cost inflation.'
    else:basis['maintenance_pct']+=' Basis: scheduled annual rent.'


def maintenance_monthly(a, rent, year=0):
    if a.get('maintenance_basis','rent')=='value':
        value=a.get('_maintenance_value')
        if value is None:return None
        return value*a['maintenance_pct']/100/12*(1+a['cost_growth_pct']/100)**year
    return rent*a['maintenance_pct']/100 if rent is not None else None
