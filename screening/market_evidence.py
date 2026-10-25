"""Turn saved provider observations into dated, scoped report evidence."""
import re
from datetime import date, datetime
from .providers import numeric, pd_comparables, rent_data
from .evidence import address_key, matched_profile, local_growth
from .schema import api_property_type


def hydrate_comparables(evidence):
    """Also recover previously unused rows from old snapshots, without new requests."""
    rows = list(evidence.get('comparables', []))
    for endpoint, kind in [('rents', 'rent'), ('sold-prices', 'sold'), ('prices-per-sqf', 'asking'),
                           ('sold-prices-per-sqf', 'sold'), ('prices', 'asking')]:
        raw = evidence.get('raw', {}).get(endpoint)
        if not isinstance(raw, dict): continue
        try:
            observed = next((s.get('retrieved_at') for s in evidence.get('sources', []) if s['id'] == endpoint), evidence.get('retrieved_at'))
            rows.extend(dict(c, observed_at=observed) for c in pd_comparables(raw, kind, endpoint))
        except (ValueError, TypeError): continue
    unique = {}
    for row in rows:
        if not row.get('address') or not numeric(row.get('amount')): continue
        listing = row.get('source_url', '') if row['kind'] != 'sold' else ''
        key = (row['kind'], address_key(row['address']), row['amount'], row.get('date', ''), listing)
        if key not in unique: unique[key] = dict(row)
        else:
            for field, value in row.items():
                if unique[key].get(field) in (None, '') and value not in (None, ''): unique[key][field] = value
    evidence['comparables'] = list(unique.values())


def usable_asking_count(inputs, evidence):
    p = inputs['property']
    return sum(1 for c in evidence.get('comparables', []) if c.get('kind') == 'asking'
               and c.get('bedrooms') == p['bedrooms'] and c.get('property_type') == api_property_type(p)
               and (not c.get('floor_area_sqm') or not p.get('floor_area_sqm') or .75 <= c['floor_area_sqm']/p['floor_area_sqm'] <= 1.25))


def usable_sold_count(inputs, evidence):
    """Conservative evidence threshold for skipping the broader paid search.

    These are still candidates for analyst review, not verified comparables.
    Missing facts never qualify a sale for this credit-saving shortcut.
    """
    from .comparisons import recent_sale
    p = inputs['property']
    subject_area = numeric(p.get('floor_area_sqm'))
    if not subject_area or subject_area <= 0: return 0
    identity = matched_profile({'inputs': inputs, 'evidence': evidence}).get('identity', {})
    subject_keys = {address_key(p['address']), address_key(p['address'], p['postcode'])}
    if identity.get('address'): subject_keys.add(address_key(identity['address']))
    seen = set()
    for c in evidence.get('comparables', []):
        if c.get('kind') != 'sold' or not c.get('address'): continue
        key = address_key(c['address'])
        if key in subject_keys: continue
        amount, area, distance = (numeric(c.get(k)) for k in ('amount', 'floor_area_sqm', 'distance'))
        if amount is None or amount <= 0 or area is None or not .75 <= area / subject_area <= 1.25: continue
        # Zero distance can be the subject property (including an address alias).
        if distance is None or not 0 < distance <= 1: continue
        if c.get('property_type') != api_property_type(p) or numeric(c.get('bedrooms')) != p['bedrooms']: continue
        if p['tenure'] in ('freehold', 'leasehold') and c.get('tenure') != p['tenure']: continue
        if p.get('new_build') and c.get('transaction_class') != 'new_build': continue
        if not str(c.get('source_url', '')).startswith(('http://', 'https://')): continue
        try: age = (date.today() - date.fromisoformat(str(c.get('date', '')))).days
        except ValueError: continue
        if not recent_sale(c): continue
        seen.add(key)
    return len(seen)


def period(value):
    text = str(value or '').strip()
    for fmt in ('%Y-%m-%d', '%Y-%m', '%Y %b', '%b %Y', '%B %Y', '%Y %B'):
        try: return datetime.strptime(text[:10] if fmt == '%Y-%m-%d' else text, fmt).date().replace(day=1)
        except ValueError: pass
    return None


def region_key(value):
    key = re.sub(r'[^a-z]', '', str(value).lower().replace('&', 'and'))
    aliases = {'yorkshireandhumber': 'yorkshireandthehumber', 'eastofengland': 'east',
               'northeastengland': 'northeast', 'northwestengland': 'northwest',
               'southeastengland': 'southeast', 'southwestengland': 'southwest'}
    return aliases.get(key, key)


def regional_rent_growth(evidence):
    result = {'rate': None, 'region': evidence.get('location', {}).get('region'), 'period': None,
              'source_id': 'national-data', 'reason': 'Regional rent inflation unavailable; no growth assumed'}
    region = region_key(result['region'])
    if not region:
        result['reason'] = 'Region could not be verified; regional rent inflation is not used'
        return result
    raw = evidence.get('raw', {}).get('national-data', evidence.get('market', {}).get('national-data', {}))
    if not isinstance(raw, dict) or raw.get('dataset') != 'rent-inflation-by-english-region': return result
    # The named dataset is annual percentage change. Never infer growth from rent levels.
    updated = raw.get('updated')
    candidates = []
    def add(value, stamp, date_basis='Observation'):
        value, stamp = numeric(value), period(stamp)
        if value is not None and stamp: candidates.append((stamp, value, date_basis))
    data = raw.get('data', [])
    if isinstance(data, dict):
        # Region-keyed series; each value still needs its own period or publication date.
        data = [{'label': k, 'data': v} if isinstance(v, list) else {'label': k, 'value': v} for k, v in data.items()]
    for row in data if isinstance(data, list) else []:
        if not isinstance(row, dict): continue
        label = row.get('region', row.get('label', row.get('name')))
        if region_key(label) == region:
            series = row.get('data', row.get('values'))
            if isinstance(series, list):
                for point in series:
                    if isinstance(point, dict): add(point.get('value'), point.get('date', point.get('label')))
                    elif isinstance(point, list) and len(point) == 2: add(point[1], point[0])
            else: add(row.get('value'), row.get('date', row.get('period', updated)), 'Observation' if row.get('date') or row.get('period') else 'Dataset updated')
        # A dated row can also carry explicitly named regional columns.
        columns = row.get('value') if isinstance(row.get('value'), dict) else row
        for name, value in columns.items():
            if region_key(name) == region: add(value, row.get('date', row.get('label')))
    if not candidates:
        result['reason'] = 'No dated rental-inflation observation matched '+str(result['region'])
        return result
    latest = max(x[0] for x in candidates)
    values = {x[1] for x in candidates if x[0] == latest}
    result['period'] = latest.isoformat()[:7]
    if len(values) != 1:
        result['reason'] = 'Conflicting regional rental-inflation observations require review'
        return result
    rate = values.pop()
    result['date_basis'] = 'Observation' if any(x[0] == latest and x[2] == 'Observation' for x in candidates) else 'Dataset updated'
    age = (date.today().year-latest.year)*12 + date.today().month-latest.month
    if age < 0 or age > 18 or not -20 <= rate <= 20:
        result['reason'] = 'Regional rent inflation is stale, future-dated or outside the automatic scenario range; review required'
        return result
    result.update(rate=round(rate, 2), reason='Scenario extends '+str(result['region'])+' annual rental inflation ('+result['date_basis'].lower()+' '+result['period']+') [national-data]. Regional history, not a property forecast; future rent increases are not assured.')
    return result


def annualised(series):
    if len(series) < 2: return None
    first, last = series[0], series[-1]
    start, end = period(first['month']), period(last['month'])
    if not start or not end: return None
    if end > date.today().replace(day=1): return None
    months = (end.year-start.year)*12 + end.month-start.month
    if months < 24: return None
    rate = ((last['value']/first['value']) ** (12/months)-1)*100
    return round(rate, 2) if -20 <= rate <= 20 else None


def growth_check(evidence):
    price, psf = local_growth(evidence), local_growth(evidence, 'growth-psf')
    common = {x['month'] for x in price} & {x['month'] for x in psf}
    a = annualised([x for x in price if x['month'] in common])
    b = annualised([x for x in psf if x['month'] in common])
    return {'price_rate': a, 'psf_rate': b, 'psf_series': psf,
            'from': min(common) if common else None, 'to': max(common) if common else None,
            'material_difference': a is not None and b is not None and (abs(a-b) >= 2 or a*b < 0)}


def sample_context(evidence, endpoint):
    raw = evidence.get('raw', {}).get(endpoint, {})
    multiplier = 1
    try:
        if endpoint == 'rents': data, _, multiplier = rent_data(raw)
        else: data = raw.get('data', {})
    except ValueError: data = {}
    if not isinstance(data, dict): data = {}
    bounds = data.get('80pc_range', [])
    bounds = [numeric(x) for x in bounds] if isinstance(bounds, list) else []
    return {'count': numeric(data.get('points_analysed')), 'radius_miles': numeric(data.get('radius')),
            'unit': 'GBP/month' if endpoint == 'rents' else ('GBP/sqft' if endpoint.endswith('-per-sqf') else 'GBP'),
            'range_80': [round(x*multiplier, 2) for x in bounds] if len(bounds) == 2 and all(x is not None and x > 0 for x in bounds) else [],
            'earliest': data.get('date_earliest'), 'latest': data.get('date_latest'), 'source_id': endpoint}


def demand_context(evidence, endpoint):
    raw = evidence.get('market', {}).get(endpoint, {})
    if not isinstance(raw, dict): return {'rating': None, 'metrics': []}
    fields = [('total_for_sale', 'Homes for sale'), ('total_for_rent', 'Homes advertised to rent'),
              ('average_sales_per_month', 'Average sales / month'), ('average_lets_per_month', 'Average lets / month'),
              ('months_of_inventory', 'Months of inventory'), ('days_on_market', 'Days on market'),
              ('turnover_per_month', 'Monthly turnover'), ('radius', 'Radius (miles)')]
    return {'rating': raw.get('rental_demand_rating', raw.get('demand_rating')),
            'metrics': [{'label': label, 'value': raw[key]} for key, label in fields if raw.get(key) is not None], 'source_id': endpoint}


def property_context(inputs, evidence):
    profile = matched_profile({'inputs': inputs, 'evidence': evidence})
    constraints = profile.get('constraints', {})
    council = profile.get('council_tax', {})
    facts = []
    flags = []
    if council.get('data_status') == 'found':
        charge = numeric(council.get('annual_charge'))
        facts.append({'label': 'Council tax', 'value': 'Band '+str(council.get('band') or 'unknown')+(('; £{:,.0f} / year'.format(charge)) if charge else '')+' — confirm current charge', 'source_id': 'property'})
    else: facts.append({'label': 'Council tax', 'value': 'Unavailable'})
    researched_council = evidence.get('researched_facts',{}).get('property.council_tax')
    if researched_council and not council.get('band'):
        facts[-1]={'label':'Council tax','value':researched_council['text'],'source_id':researched_council['source_ids'][0]}
    flood = constraints.get('flood_risk', {})
    risk = flood.get('flood_risk') if flood.get('data_status') == 'found' else None
    researched_flood = evidence.get('researched_facts',{}).get('constraint.flood_risk')
    if not risk and researched_flood:
        risk = researched_flood['value']
    facts.append({'label': 'River / sea flood risk', 'value': str(risk or 'Unresolved'), 'source_id': 'property' if risk else None})
    if researched_flood and flood.get('data_status') != 'found': facts[-1]['source_id'] = researched_flood['source_ids'][0]
    surface = evidence.get('researched_facts',{}).get('constraint.surface_water_flood_risk')
    facts.append({'label':'Surface-water flood risk','value':surface['text'] if surface else 'Unresolved; river / sea risk does not establish surface-water risk','source_id':surface['source_ids'][0] if surface else None})
    listed = evidence.get('researched_facts',{}).get('constraint.listed')
    if listed: facts.append({'label':'Subject listed-building status', 'value':listed['text'], 'source_id':listed['source_ids'][0]})
    if risk and str(risk).lower() not in ('low', 'very low'):
        flags.append({'level': 'warning', 'title': 'Flood evidence needs review', 'detail': 'The matched profile reports '+str(risk)+' river / sea flood risk. Check detailed searches and insurance terms.'})
    for field, label in [('conservation_area', 'Conservation area'), ('green_belt', 'Green belt'), ('aonb', 'National landscape'), ('national_park', 'National park')]:
        part = constraints.get(field, {})
        value = part.get(field) if part.get('data_status') == 'found' else None
        name = part.get(field+'_name', part.get('name'))
        text = ('Yes'+(' — '+str(name) if name else '')) if value is True else ('No — the matched PropertyData record reports the property outside this designation' if value is False else 'Unavailable / inconclusive')
        researched = evidence.get('researched_facts', {}).get('constraint.'+field)
        if value is None and researched:
            value = researched['value']
            text = ('Identified' if value else 'Not identified by the cited official evidence')+'; '+researched['text']
            facts.append({'label': label, 'value': text, 'source_id': researched['source_ids'][0]})
        else:
            if value is None:
                finding = next((f for f in evidence.get('research',{}).get('findings',[]) if f.get('gap_id') == 'constraint.'+field), None)
                text = 'Unresolved after provider and web research' if finding else 'Unresolved; fallback research has not completed'
            facts.append({'label': label, 'value': text, 'source_id': 'property' if value is not None else None})
        if value is True:
            flags.append({'level': 'warning', 'title': label+' recorded', 'detail': 'Check restrictions with the local authority before assuming alterations or development are possible.'})
    listed = constraints.get('listed_buildings_nearby', {})
    nearby = listed.get('listed_buildings', []) if listed.get('data_status') == 'found' else None
    subject_text = '; subject status is stated separately' if evidence.get('researched_facts',{}).get('constraint.listed') else '; subject listing status unverified'
    facts.append({'label': 'Nearby listed buildings', 'value': (str(len(nearby))+' returned' if isinstance(nearby, list) else 'Unavailable')+subject_text, 'source_id': 'property' if nearby is not None else None})
    planning_raw = evidence.get('raw', {}).get('planning-applications')
    planning = {'requested': planning_raw is not None or any(x['id'] == 'planning-applications' for x in evidence.get('sources', [])), 'rows': [], 'basis': evidence.get('planning_basis', '')}
    if isinstance(planning_raw, dict):
        rows = planning_raw.get('applications', planning_raw.get('data', []))
        if isinstance(rows, dict): rows = rows.get('planning_applications', rows.get('applications', []))
        if isinstance(rows, list):
            for row in rows[:10]:
                if not isinstance(row, dict): continue
                item = {k: row.get(k) for k in ('address', 'reference', 'url', 'distance')}
                item['description'] = row.get('proposal', row.get('description'))
                item['date'] = row.get('dates', {}).get('received_at', row.get('date'))
                item['decision'] = row['decision'].get('text') if isinstance(row.get('decision'), dict) else row.get('decision', row.get('status'))
                planning['rows'].append(item)
    return {'facts': facts, 'flags': flags, 'planning': planning,
            'council_tax_note': 'Council tax is a property reference. The vacancy-cost allowance covers empty-period bills; this charge is not added again to annual operating costs.'}
