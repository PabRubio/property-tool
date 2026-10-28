"""Conservative property identity checks for report facts and sale history."""
import re
import copy
from datetime import datetime
from .providers import numeric
from .schema import iso_date, defaults, api_property_type


def identity_matches(p, identity):
    if p.get('uprn'):
        return str(identity.get('uprn', '')) == p['uprn']
    if identity.get('address') and address_key(identity['address']) == address_key(p['address'], p['postcode']):
        return True
    parts = identity.get('address_parts', {})
    # Never strip a flat/unit identifier to make a match. House aliases and town
    # variations are safe only with the same postcode, numbered street and no unit.
    if parts.get('secondary') or api_property_type(p) == 'flat': return False
    if address_key(parts.get('postcode', '')) != address_key(p['postcode']): return False
    primary, street = parts.get('primary'), parts.get('street')
    if not primary or not street or not re.fullmatch(r'\d+[A-Za-z]?', str(primary)): return False
    clean = lambda s: re.sub(r'[^A-Z0-9 ]', ' ', str(s).upper())
    target = ' '.join(clean(str(primary)+' '+street).split())
    entered = ' '.join(clean(p['address']).split())
    if re.search(r'\b(FLAT|APARTMENT|UNIT|ROOM)\b', entered): return False
    # Extra numbers can indicate a flat number or a building range.
    if re.findall(r'\b\d+[A-Z]?\b', entered) != [str(primary).upper()]: return False
    return bool(re.search(r'(?<!\w)'+re.escape(target)+r'(?!\w)', entered))


def address_key(address, postcode=''):
    key = re.sub(r'[^A-Z0-9]', '', str(address).upper())
    pc = re.sub(r'[^A-Z0-9]', '', str(postcode or '').upper())
    return key if not pc or key.endswith(pc) else key + pc


def matched_profile(record):
    p = record['inputs']['property']
    profile = record['evidence'].get('profile', {})
    identity = profile.get('identity', {})
    if identity.get('data_status') != 'found':
        return {}
    if identity_matches(p, identity):
        return profile
    return {}


def property_history(record):
    p, evidence = record['inputs']['property'], record['evidence']
    target = address_key(p['address'], p['postcode'])
    rows = []
    candidates = evidence.get('history_candidates', []) + evidence.get('comparables', [])
    candidates += [c for c in record['inputs']['comparables'] if c['selected']]
    for c in candidates:
        if c.get('kind') == 'sold' and address_key(c.get('address', '')) == target:
            rows.append(dict(c, source_id=c.get('source_id') or ('land-registry-history' if c.get('source', '').startswith('HM Land') else 'inputs')))
    profile = matched_profile(record)
    sales = profile.get('sales', {})
    if sales.get('data_status') == 'found':
        for tx in sales.get('transactions', []):
            txid = str(tx.get('transaction_id', '')).strip('{}')
            url = 'https://landregistry.data.gov.uk/app/ppd/'
            if re.fullmatch(r'[a-fA-F0-9-]{36}', txid):
                url = 'https://landregistry.data.gov.uk/data/ppi/transaction/' + txid
            rows.append({'date': tx.get('date'), 'amount': tx.get('price'), 'source': 'HM Land Registry via PropertyData', 'source_id': 'property', 'source_url': url})
    valid, seen = [], set()
    for row in rows:
        amount = numeric(row.get('amount'))
        try:
            date = iso_date(str(row.get('date', ''))[:10], 'Sale date', optional=False)
        except ValueError:
            continue
        if amount is None or amount <= 0 or (date, amount) in seen:
            continue
        seen.add((date, amount))
        valid.append(dict(row, amount=amount, date=date))
    return sorted(valid, key=lambda r: r['date'], reverse=True)


def enriched_inputs(inputs, evidence):
    out = copy.deepcopy(inputs)
    for group in ('property', 'assumptions', 'investor', 'enquiry'):
        out[group] = dict(defaults()[group], **out.get(group, {}))
    for path, source in list(out.get('input_provenance',{}).items()):
        if path.startswith('property.') and source.get('source_id','').startswith('research-'):
            out['property'][path.split('.',1)[1]] = defaults()['property'][path.split('.',1)[1]]
            out['input_provenance'].pop(path,None)
    # Research facts fill unknowns only. Preserve client facts and conflicting evidence.
    choices = {'construction_date': ('pre_1914','1914_2000','2000_onwards'), 'epc_rating': tuple('ABCDEFG'),
               'tenure': ('freehold','leasehold'), 'finish_quality': ('very_high','high','average','below_average','unmodernised'),
               'outdoor_space': ('none','balcony_terrace','garden','garden_very_large')}
    ranges = {'floor_area_sqm': (1,10000), 'bathrooms': (0,5), 'off_street_parking': (0,3), 'lease_years': (0,999)}
    for path, fact in evidence.get('researched_facts', {}).items():
        if not path.startswith('property.'): continue
        key = path.split('.',1)[1]; value = fact.get('value')
        valid = value in choices[key] if key in choices else (key in ranges and not isinstance(value,bool) and isinstance(value,(float,int)) and ranges[key][0] <= value <= ranges[key][1])
        if key in ('bathrooms','off_street_parking') and valid: valid = value % 1 == 0
        if valid and out['property'].get(key) in (None,'','unknown'):
            out['property'][key] = value
            out.setdefault('input_provenance',{})[path] = {'basis':'Cited web research', 'source_id':fact['source_ids'][0], 'recorded_at':fact['retrieved_at']}
    # A fresh research snapshot must refresh previously derived facts too. Explicit
    # client/analyst corrections have their own provenance and remain untouched.
    for path, source in list(out.get('input_provenance', {}).items()):
        if not path.startswith('property.') or source.get('source_id') not in ('property', 'title', 'floor-areas', 'energy-efficiency'): continue
        key = path.split('.', 1)[1]
        if key in defaults()['property'] and source.get('recorded_at') != evidence.get('retrieved_at'):
            out['property'][key] = defaults()['property'][key]
            out['input_provenance'].pop(path, None)
    profile = matched_profile({'inputs': out, 'evidence': evidence})
    p = out['property']; building = profile.get('building', {})
    proposed = {}
    if building.get('data_status') == 'found':
        area = numeric(building.get('internal_area_sqf'))
        if area and 10.7639 <= area <= 107639: proposed['floor_area_sqm'] = round(area / 10.7639104167, 2)
        if building.get('energy_rating') in list('ABCDEFG'): proposed['epc_rating'] = building['energy_rating']
        years = [int(x) for x in re.findall(r'\b(?:18|19|20)\d{2}\b', str(building.get('construction_age_band', '')))]
        if years and max(years) < 1914: proposed['construction_date'] = 'pre_1914'
        elif years and min(years) >= 1914 and max(years) < 2000: proposed['construction_date'] = '1914_2000'
        elif years and min(years) >= 2000: proposed['construction_date'] = '2000_onwards'
    title = profile.get('title', {})
    tenures = {t.get('tenure') for t in title.get('titles', [])} if title.get('data_status') == 'found' else set()
    if len(tenures) == 1 and next(iter(tenures)) in ('freehold', 'leasehold'): proposed['tenure'] = next(iter(tenures))
    for key, value in proposed.items():
        if p.get(key) in (None, '', 'unknown'):
            p[key] = value
            out.setdefault('input_provenance', {})['property.'+key] = {'basis': 'Matched property profile', 'source_id': 'property', 'recorded_at': evidence.get('retrieved_at')}
    # Postcode lists must match the full subject identity; proximity is not a match.
    for endpoint, field, container in [('floor-areas', 'floor_area_sqm', 'floor_areas'), ('energy-efficiency', 'epc_rating', 'energy_efficiency')]:
        if p.get(field) not in (None, '', 'unknown'): continue
        raw = evidence.get('raw', {}).get(endpoint, {})
        data = raw.get('data', raw)
        rows = data.get(container, []) if isinstance(data, dict) else data
        found = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or not fallback_identity(p, profile, row, raw.get('postcode')): continue
            if field == 'epc_rating': value = row.get('rating', row.get('energy_rating'))
            else:
                value = numeric(row.get('floor_area_sqm'))
                if value is None:
                    sqf = numeric(row.get('floor_area_sqf', row.get('sqf')))
                    value = round(sqf / 10.7639104167, 2) if sqf else None
            if (field == 'epc_rating' and value in list('ABCDEFG')) or (field == 'floor_area_sqm' and value and 1 <= value <= 10000):
                found.append((str(row.get('inspection_date', '')), value))
        if found:
            latest = max(x[0] for x in found)
            values = {x[1] for x in found if x[0] == latest}
            if len(values) == 1:
                p[field] = values.pop()
                out.setdefault('input_provenance', {})['property.'+field] = {'basis': 'Exact property match', 'source_id': endpoint, 'recorded_at': evidence.get('retrieved_at')}
    if p.get('tenure') == 'leasehold' and p.get('lease_years') is None:
        for source, data in [('property', title), ('title', evidence.get('raw', {}).get('title', {}).get('data', {}))]:
            if source == 'property' and title.get('data_status') != 'found': continue
            if source == 'title':
                number = fallback_title(out, evidence)
                if not number or evidence.get('raw', {}).get('title', {}).get('title_number') != number: continue
            years = lease_years(data, p, profile)
            if years is not None:
                p['lease_years'] = years
                out.setdefault('input_provenance', {})['property.lease_years'] = {'basis': 'Unambiguous matched lease; verify with solicitor', 'source_id': source, 'recorded_at': evidence.get('retrieved_at')}
                break
    return out


def fallback_identity(p, profile, row, postcode=None):
    target = dict(p)
    identity = profile.get('identity', {})
    if identity.get('uprn'): target['uprn'] = str(identity['uprn'])
    if row.get('uprn') and target.get('uprn'): return str(row['uprn']) == str(target['uprn'])
    # List endpoints often have no UPRN: require exact address, including the postcode.
    keys = {address_key(p['address'], p['postcode'])}
    if identity.get('address'): keys.add(address_key(identity['address'], p['postcode']))
    return bool(row.get('address') and address_key(row['address'], row.get('postcode') or postcode or '') in keys)


def fallback_title(inputs, evidence):
    p = inputs['property']
    if p.get('tenure') != 'leasehold' or p.get('lease_years') is not None: return None
    profile = matched_profile({'inputs': inputs, 'evidence': evidence})
    titles = profile.get('title', {})
    if titles.get('data_status') != 'found': return None
    numbers = {x.get('title_number') for x in titles.get('titles', []) if x.get('tenure') == 'leasehold' and x.get('title_number')}
    return next(iter(numbers)) if len(numbers) == 1 else None


def lease_years(data, p, profile):
    if not isinstance(data, dict): return None
    rows = data.get('distinctLeases', data.get('registeredLeases', data.get('registered_leases', [])))
    if not isinstance(rows, list): return None
    found = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict): continue
        addresses = row.get('associated_addresses', row.get('addresses', []))
        if row.get('address'): addresses = [row['address']] + (addresses if isinstance(addresses, list) else [])
        if not isinstance(addresses, list): continue
        if addresses and not any(fallback_identity(p, profile, x if isinstance(x, dict) else {'address': x}, p['postcode']) for x in addresses): continue
        # A lone lease on a matched profile may have no address; multiple leases stay ambiguous.
        if not addresses and len(rows) != 1: continue
        years = numeric(row.get('years_remaining'))
        if years is None or not 0 <= years <= 999: continue
        key = ('lease', row['lease_id']) if row.get('lease_id') else ('unidentified', index)
        found.setdefault(key, set()).add(int(years))
    if len(found) == 1:
        values = next(iter(found.values()))
        if len(values) == 1: return next(iter(values))
    return None


def local_growth(evidence, source='growth'):
    raw = evidence.get('market', {}).get(source, [])
    if isinstance(raw, dict): raw = raw.get('data', [])
    rows = []
    if not isinstance(raw, list): return rows
    for row in raw:
        if not isinstance(row, list) or len(row) < 2: continue
        try: month = datetime.strptime(str(row[0]), '%b %Y').strftime('%Y-%m')
        except ValueError: continue
        value = numeric(row[1])
        if value and value > 0: rows.append({'month': month, 'value': value})
    return sorted(rows, key=lambda r: r['month'])


def ranked_comparables(record, kind):
    p = record['inputs']['property']
    rows = [copy.deepcopy(c) for c in record['evidence'].get('comparables', []) if c['kind'] == kind]
    def rank(c):
        bed = c.get('bedrooms')
        area = c.get('floor_area_sqm')
        mismatch = (bed is not None and bed != p['bedrooms']) or (c.get('property_type') and c['property_type'] != api_property_type(p))
        distance = numeric(c.get('distance'))
        if distance is None:
            m = re.search(r'Distance reported: (\d+(?:\.\d+)?)', c.get('notes', ''))
            distance = numeric(m.group(1)) if m else None
        size_gap = abs(area / p['floor_area_sqm'] - 1) if area and p.get('floor_area_sqm') else 1
        return (bool(mismatch), bed is None, size_gap, distance if distance is not None else 999, c.get('address', ''))
    return sorted(rows, key=rank)


def valuation(evidence, kind):
    """Only use numeric provider values with explicit units for rents."""
    d = evidence.get('market', {}).get('valuation-'+kind, {})
    if not isinstance(d, dict): return None
    estimate = numeric(d.get('estimate'))
    if not estimate or estimate <= 0: return None
    if kind == 'rent':
        unit = str(d.get('unit', '')).lower()
        if unit in ('gbp_per_week', 'weekly', 'week', 'pw', 'per week', 'gbp/week', '£pw', '£ per week'): estimate *= 52 / 12
        elif unit not in ('gbp_per_month', 'monthly', 'month', 'pcm', 'per month', 'gbp/month', '£pcm', '£ per month'): return None
    return round(estimate, 2)


def clear_profile_inputs(new, old):
    """An address edit must not carry derived facts over to a different property."""
    for path, source in old.get('input_provenance', {}).items():
        if source.get('source_id') not in ('property', 'title', 'floor-areas', 'energy-efficiency') or not path.startswith('property.'): continue
        key = path.split('.', 1)[1]
        if new['property'].get(key) == old['property'].get(key):
            new['property'][key] = defaults()['property'][key]
            new.get('input_provenance', {}).pop(path, None)


def invalidate_size_evidence(evidence):
    """Size-filtered samples cannot be reused after an area correction."""
    endpoints = ('prices-per-sqf', 'sold-prices-per-sqf')
    for endpoint in endpoints: evidence.get('raw', {}).pop(endpoint, None)
    for key in ('asking_price_per_sqft', 'sold_price_per_sqft'): evidence.get('market', {}).pop(key, None)
    evidence['sources'] = [s for s in evidence.get('sources', []) if s['id'] not in endpoints]
    evidence['comparables'] = [c for c in evidence.get('comparables', []) if c.get('source_id') not in endpoints]
