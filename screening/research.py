"""Gap-driven, cited web research. Search results remain evidence, never instructions."""
import copy
import hashlib
import json
from urllib.parse import urlsplit
from .providers import now
from .evidence import matched_profile, enriched_inputs, identity_matches, address_key, property_history
from .comparisons import comparison_summary
from .commercial import is_commercial

LABELS = {'conservation_area': 'Conservation area', 'green_belt': 'Green belt', 'aonb': 'National landscape',
          'national_park': 'National park', 'flood_risk': 'River / sea flood risk',
          'surface_water_flood_risk': 'Surface-water flood risk', 'listed': 'Listed building status'}


def gaps(record):
    inputs = enriched_inputs(record['inputs'], record['evidence'])
    p, a = inputs['property'], inputs['assumptions']
    profile = matched_profile({'inputs': inputs, 'evidence': record['evidence']})
    result = []
    for field, label in LABELS.items():
        part = profile.get('constraints', {}).get(field, {})
        if part.get('data_status') != 'found' or part.get(field) is None:
            result.append({'id': 'constraint.'+field, 'label': label, 'group': 'property', 'provider_result': 'No conclusive matched property observation'})
    if is_commercial(inputs):
        for field in ('floor_area_sqm', 'floor_area_basis', 'epc_rating', 'tenure', 'lease_years', 'use_class'):
            if field == 'lease_years' and p['tenure'] == 'freehold': continue
            if p.get(field) in (None, '', 'unknown'):
                result.append({'id': 'property.' + field, 'label': 'Commercial ' + field.replace('_', ' '), 'group': 'property', 'provider_result': 'Not supplied or verified; non-domestic evidence required'})
        for kind in ('rent', 'sold', 'asking'):
            result.append({'id': 'comparisons.' + kind, 'label': 'Commercial ' + p['property_type'] + ' ' + kind + ' comparisons: area measurement, lease terms and VAT basis required', 'group': 'comparisons', 'provider_result': 'Commercial automated estimates are not completed transactions'})
        result.extend([
            {'id': 'property.business_rates', 'label': 'Subject rateable value and business-rate context; not an automatic landlord cost or relief entitlement', 'group': 'property', 'provider_result': 'Unverified'},
            {'id': 'property.lease_terms', 'label': 'Published commercial lease, tenant covenant and repair/insurance responsibilities; private terms may remain unknown', 'group': 'property', 'provider_result': 'Actual lease requires client documents'},
            {'id': 'property.nearby_places', 'label': 'Nearby transport, access, commercial setting and useful amenities', 'group': 'context', 'provider_result': 'Unverified'},
            {'id': 'costs', 'label': 'Commercial letting, repair, legal and survey cost context; no residential RICS Home Survey allowances', 'group': 'context', 'provider_result': 'Supplied landlord budgets take precedence'},
            {'id': 'planning', 'label': 'Subject planning use and relevant permissions; nearby applications do not confirm subject permission', 'group': 'property', 'provider_result': 'Unverified'},
        ])
        if not property_history(record): result.append({'id': 'history', 'label': 'Exact commercial subject sale history', 'group': 'property', 'provider_result': 'No verified transaction'})
        return result
    for field in ('floor_area_sqm', 'bathrooms', 'construction_date', 'epc_rating', 'tenure', 'lease_years', 'finish_quality', 'outdoor_space', 'off_street_parking'):
        if field == 'lease_years' and p['tenure'] == 'freehold': continue
        if p.get(field) in (None, '', 'unknown'):
            result.append({'id': 'property.'+field, 'label': field.replace('_', ' '), 'group': 'property', 'provider_result': 'Not supplied or not matched'})
    if not profile.get('council_tax',{}).get('band'):
        result.append({'id':'property.council_tax','label':'Council tax band and current charge','group':'property','provider_result':'No matched council tax band'})
    if not profile.get('building',{}).get('floor_level') and p['property_type'] in ('flat','converted_flat','studio'):
        result.append({'id':'property.floor_level','label':'Floor level of this flat','group':'property','provider_result':'No matched floor level'})
    if profile.get('building',{}).get('habitable_rooms'):
        result.append({'id':'property.room_layout','label':'Room-by-room layout explaining habitable rooms versus bedrooms','group':'property','provider_result':'A total room count does not identify each room'})
    for kind in ('rent', 'sold', 'asking'):
        summary = comparison_summary(inputs, record['evidence'], 'sold' if kind == 'sold' else 'rent') if kind != 'asking' else None
        result.append({'id': 'comparisons.'+kind, 'label': 'Five best '+kind+' comparisons, including missing bedroom counts', 'group': 'comparisons',
                       'provider_result': str(summary['count'])+' sufficiently matched comparisons' if summary else 'Asking prices are separate from completed sales'})
    if not property_history(record): result.append({'id': 'history', 'label': 'Exact subject sale history', 'group': 'property', 'provider_result': 'No matched sales'})
    result.append({'id':'property.nearby_places','label':'Nearby transport, shops, parks and other useful amenities: concise cited locality context; distances or travel times only when evidenced',
                   'group':'context','provider_result':'Administrative ward names do not establish nearby amenities'})
    # Research evidence for default budgets too. A generic quote is not silently
    # turned into a property-specific annual cost without frequency and scope.
    result.append({'id': 'costs', 'label': 'Local regular cleaning, tenancy changeover cleaning and operating-cost evidence', 'group': 'context', 'provider_result': 'Budgets need scope and quotes'})
    for field in ('growth', 'national-data', 'demand', 'demand-rent'):
        if not any(s.get('id') == field and s.get('status') == 'ok' for s in record['evidence'].get('sources', [])):
            result.append({'id': 'context.'+field, 'label': field, 'group': 'context', 'provider_result': 'No usable provider observation'})
    if a.get('refurbishment_planned'):
        result.append({'id': 'planning', 'label': 'Subject planning applications / relevant restrictions', 'group': 'property', 'provider_result': 'Nearby applications do not establish subject consent'})
        if a.get('after_works_value') is None:
            result.append({'id':'assumptions.after_works_value','label':'Supported subject value after the specified works; only a sourced valuation of that condition and scope','group':'property','provider_result':'No supplied after-works value; do not infer value from cost'})
    return result


FINDING = {'type': 'object', 'properties': {
    'gap_id': {'type':'string'}, 'status': {'type':'string', 'enum':['supported','inconclusive']},
    'text': {'type':'string'}, 'value_json': {'type':'string'}, 'source_ids': {'type':'array','items':{'type':'string'}},
    'matched_address': {'type':'string'}, 'matched_postcode': {'type':'string'}, 'evidence_date': {'type':'string'},
    'scope': {'type':'string','enum':['subject','comparison','area','cost']}, 'limitations': {'type':'string'}},
    'required':['gap_id','status','text','value_json','source_ids','matched_address','matched_postcode','evidence_date','scope','limitations'], 'additionalProperties':False}


def apply_findings(record, requested, result, extracted, batch):
    e = record['evidence']; sources = {s['id']:s for s in result['sources']}
    mapped = {}
    for source in sources.values():
        sid = 'research-'+hashlib.sha256(source['url'].encode()).hexdigest()[:10]
        mapped[source['id']] = sid
        if not any(s['id'] == sid for s in e['sources']):
            e['sources'].append(dict(source, id=sid, retrieved_at=now(), status='ok', scope='AI web research; see claim-specific match and limitations'))
    requested = {g['id']:g for g in requested}; processed = set(); findings = []
    p = record['inputs']['property']
    for f in extracted.get('findings', []):
        if not isinstance(f, dict) or f.get('gap_id') not in requested or f['gap_id'] in processed: continue
        processed.add(f['gap_id']); f = copy.deepcopy(f)
        refs = f.get('source_ids', [])
        good = bool(refs) and all(ref in sources for ref in refs)
        try: value = json.loads(f.get('value_json','null'))
        except (ValueError, TypeError): value = None
        supported = f.get('status') == 'supported' and good and value is not None
        topic = f['gap_id']; f['source_ids'] = [mapped[x] for x in refs if x in mapped]
        f['provider_result'] = requested[topic]['provider_result']; f['searched_at'] = now()
        identity = {'address': f.get('matched_address', ''), 'address_parts': {'postcode': f.get('matched_postcode', '')}}
        subject_match = identity_matches(p, identity) or bool(f.get('matched_address') and f.get('matched_postcode')
            and address_key(f['matched_address'], f['matched_postcode']) == address_key(p['address'], p['postcode']))
        if topic=='property.nearby_places':
            # Local amenities describe the postcode area, not a surveyed house fact.
            supported = supported and f.get('scope') in ('area','subject') and address_key(f.get('matched_postcode',''))==address_key(p['postcode'])
            supported = supported and isinstance(value,str) and 0 < len(value.strip()) <= 900
            if supported:e.setdefault('researched_facts',{})[topic]=dict(value=value,text=value,source_ids=f['source_ids'],evidence_date=f.get('evidence_date'),retrieved_at=now(),limitations=f.get('limitations',''))
        elif topic.startswith(('property.', 'constraint.')) or topic=='assumptions.after_works_value':
            supported = supported and f.get('scope') == 'subject' and subject_match
            if topic=='assumptions.after_works_value':
                supported = supported and not isinstance(value,bool) and isinstance(value,(int,float)) and 0 < value <= 100000000
            if topic.startswith('constraint.'):
                official = any((urlsplit(sources[x]['url']).hostname or '').endswith(('.gov.uk', '.historicengland.org.uk')) or urlsplit(sources[x]['url']).hostname == 'historicengland.org.uk' for x in refs if x in sources)
                supported = supported and official and (isinstance(value, bool) or topic.endswith('flood_risk') and isinstance(value, str))
            if supported: e.setdefault('researched_facts', {})[topic] = dict(value=value, text=f['text'], source_ids=f['source_ids'], evidence_date=f.get('evidence_date'), retrieved_at=now(), limitations=f.get('limitations',''))
        elif topic.startswith('comparisons.') or topic == 'history':
            valid = []
            for row in value if isinstance(value, list) else []:
                if not isinstance(row, dict): continue
                row_refs = row.get('source_ids', [])
                if not row_refs or any(x not in sources for x in row_refs): continue
                if row.get('source_url') not in {sources[x]['url'] for x in row_refs}: continue
                amount = row.get('amount')
                if isinstance(amount, bool) or not isinstance(amount, (int,float)) or not 0 < amount <= 100000000: continue
                if not isinstance(row.get('address'), str) or not row['address']: continue
                if row.get('kind') not in ('rent','sold','asking'): continue
                if topic.startswith('comparisons.') and row['kind'] != topic.split('.')[1]: continue
                bad = False
                for field, limit in [('bedrooms',20),('floor_area_sqm',10000),('distance',1000)]:
                    v = row.get(field)
                    if v is not None and (isinstance(v,bool) or not isinstance(v,(int,float)) or not 0 <= v <= limit): bad = True
                if bad: continue
                row.update(source_id=mapped[row_refs[0]], source_ids=[mapped[x] for x in row_refs], selected=False, source='Cited web research', research_batch=batch)
                if topic == 'history':
                    if address_key(row['address'], row.get('postcode') or '') != address_key(p['address'], p['postcode']): continue
                    e.setdefault('history_candidates', []).append(row)
                else: e.setdefault('comparables', []).append(row)
                valid.append(row)
            supported = good and bool(valid)
        f['status'] = 'supported' if supported else 'inconclusive'
        if not supported and f.get('status') != extracted.get('status'):
            f['limitations'] = (f.get('limitations','')+' Evidence must establish the exact property, scope and value; uncited or ambiguous findings are not used.').strip()
        f.pop('value_json', None); findings.append(f)
    for topic, gap in requested.items():
        if topic not in processed: findings.append(dict(gap, gap_id=topic, status='inconclusive', text='Search did not return a supported finding for this gap.', source_ids=[], limitations='Further evidence required', searched_at=now()))
    return findings


def research(record, provider, progress=lambda s:None, refresh=False):
    if record['mode'] == 'demo': return
    if provider != 'codex':
        raise ValueError('Only Codex is supported for AI research')
    from .codex_research import research as codex_research
    return codex_research(record, progress, refresh)
