import concurrent.futures
import json
import math
import os
import re
import threading
import time
from collections import deque
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, date, timedelta, timezone
from .schema import api_property_type


_paid_times = deque()
_paid_lock = threading.Lock()


def pace_paid_requests():
    # The lowest documented plan permits 12 calls per rolling 30 seconds.
    # Share the limiter across local workers; no retries consume extra credits.
    while True:
        with _paid_lock:
            stamp = time.monotonic()
            while _paid_times and stamp - _paid_times[0] >= 30.1: _paid_times.popleft()
            if len(_paid_times) < 12:
                _paid_times.append(stamp)
                return
            delay = 30.1 - (stamp - _paid_times[0])
        time.sleep(max(.01, delay))


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def scrub(value):
    if isinstance(value, dict):
        return {k: scrub(v) for k,v in value.items() if k.lower() not in ("key", "api_key", "authorization", "x-api-key", "access_token")}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"([?&](?:key|api_key|token)=)[^&\s]+", r"\1[redacted]", value, flags=re.I)
        for k in ("PROPERTYDATA_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
            if os.getenv(k):
                value = value.replace(os.environ[k], "[redacted]")
    return value


def request_json(url, params=None, headers=None, body=None, timeout=35):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    h = {"Accept": "application/json", "User-Agent": "LocalPropertyScreening/1.0"}
    h.update(headers or {})
    raw = json.dumps(body, allow_nan=False).encode() if body is not None else None
    if raw:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=raw, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(8 * 1024 * 1024 + 1)
            if len(data) > 8 * 1024 * 1024:
                raise ValueError("Provider response exceeded 8 MB")
            result = json.loads(data)
    except urllib.error.HTTPError as e:
        raise ValueError("Provider HTTP %s; check credentials, credits, model access and request inputs" % e.code)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError("Provider could not be reached or timed out; check the connection and retry")
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("Provider returned invalid JSON")
    if not isinstance(result, dict):
        raise ValueError("Unexpected provider response shape")
    return result


def pd_call(endpoint, params):
    key = os.getenv("PROPERTYDATA_API_KEY", "")
    if not key:
        raise ValueError("PROPERTYDATA_API_KEY is not configured")
    pace_paid_requests()
    raw = request_json("https://api.propertydata.co.uk/" + endpoint, params, {"X-API-Key": key})
    if raw.get("status") == "error":
        raise ValueError("PropertyData %s: %s" % (str(raw.get("code", "error"))[:30], scrub(str(raw.get("message", "Request failed")))[:350]))
    return scrub(raw)


def numeric(v):
    try:
        n = float(str(v).replace(",", ""))
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def rent_data(raw):
    d = raw.get("data", {})
    if not isinstance(d, dict):
        raise ValueError("Unrecognised rent response data")
    d = d.get("long_let", d)
    if not isinstance(d, dict):
        raise ValueError("Unrecognised long-let response")
    unit = str(d.get("unit", "weekly")).lower()
    if unit in ("week", "weekly", "pw", "per week", "gbp/week", "gbp_per_week", "£pw", "£ per week"):
        multiplier = 52 / 12
    elif unit in ("month", "monthly", "pcm", "per month", "gbp/month", "gbp_per_month", "£pcm", "£ per month"):
        multiplier = 1
    else:
        raise ValueError("Unrecognised rent unit; inspect raw data before using it")
    avg = numeric(d.get("average"))
    return d, round(avg * multiplier, 2) if avg is not None and avg > 0 else None, multiplier


def pd_comparables(raw, kind, source_id=None):
    d, multiplier = raw.get("data", {}), 1
    if kind == "rent":
        d, _, multiplier = rent_data(raw)
    rows = []
    if not isinstance(d, dict): return rows
    for c in d.get("raw_data", [])[:100]:
        if not isinstance(c, dict): continue
        amount = numeric(c.get("price"))
        if not amount or amount <= 0 or not c.get("address"):
            continue
        sqm = numeric(c.get("sqf"))
        rows.append({"kind": kind, "address": str(c["address"]), "amount": round(amount * multiplier, 2),
                     "date": str(c.get("date", ""))[:10], "source_url": str(c.get("url", "")),
                     "bedrooms": numeric(c.get("bedrooms")), "floor_area_sqm": round(sqm / 10.7639104167, 2) if sqm else None,
                     "distance": numeric(c.get("distance")), "selected": False, "source": "PropertyData / " + {"sold": "Land Registry", "rent": "advertised rent", "asking": "advertised sale"}[kind],
                     "source_id": source_id or {"sold": "sold-prices", "rent": "rents", "asking": "prices-per-sqf"}[kind],
                     "days_on_market": numeric(c.get("days_on_market")), "sstc": c.get("sstc"),
                     "tenure": c.get("tenure"), "transaction_class": c.get("class"),
                     "property_type": str(c.get("type", "")),
                     "notes": "Distance reported: %s miles. %s" % (c.get("distance", "unknown"), "Confirm property match and date." if kind == "sold" else "Advertised price, not a completed transaction.")})
    return rows


def land_registry(postcode, property_type, history=False):
    # Exact postcode avoids an unbounded district query. Sparse results remain explicit.
    types = {"flat": "flat-maisonette", "terraced_house": "terraced", "semi-detached_house": "semi-detached", "detached_house": "detached"}
    since = "1995-01-01" if history else (date.today()-timedelta(days=730)).isoformat()
    query = '''PREFIX ppi: <http://landregistry.data.gov.uk/def/ppi/>
PREFIX lr: <http://landregistry.data.gov.uk/def/common/>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT ?tx ?price ?date ?paon ?saon ?street ?town ?postcode WHERE {
?tx ppi:propertyAddress ?addr; ppi:pricePaid ?price; ppi:transactionDate ?date;
    ppi:propertyType lr:%s; ppi:transactionCategory ppi:standardPricePaidTransaction .
?addr lr:postcode %s . BIND(%s AS ?postcode)
OPTIONAL { ?addr lr:paon ?paon } OPTIONAL { ?addr lr:saon ?saon }
OPTIONAL { ?addr lr:street ?street } OPTIONAL { ?addr lr:town ?town }
FILTER(?date >= "%s"^^xsd:date)
} ORDER BY DESC(?date) LIMIT %s''' % (types[property_type], json.dumps(postcode), json.dumps(postcode), since, 200 if history else 50)
    raw = request_json("https://landregistry.data.gov.uk/landregistry/query", {"query": query, "format": "json"}, {"Accept": "application/sparql-results+json"})
    bindings = raw.get("results", {}).get("bindings")
    if not isinstance(bindings, list):
        raise ValueError("Unrecognised Land Registry response")
    rows = []
    for b in bindings:
        v = lambda k: b.get(k, {}).get("value", "")
        amount = numeric(v("price"))
        if not amount or amount <= 0:
            continue
        rows.append({"kind": "sold", "address": ", ".join(v(k) for k in ("saon", "paon", "street", "town", "postcode") if v(k)),
                     "amount": amount, "date": v("date")[:10], "source_url": v("tx"), "bedrooms": None,
                     "floor_area_sqm": None, "selected": False, "source": "HM Land Registry (direct)",
                     "property_type": property_type, "notes": "Same postcode and property type; size, condition and bedroom count are not verified. Standard transaction; last 24 months."})
    if history:
        for row in rows:
            row["notes"] = "Postcode history candidate; exact address match required. Query capped at 200 transactions since 1995."
    return {"raw": raw, "comparables": rows}


def hpi():
    query = '''PREFIX hpi: <http://landregistry.data.gov.uk/def/ukhpi/>
SELECT ?month ?index ?price WHERE {
?obs hpi:refRegion <http://landregistry.data.gov.uk/id/region/england>;
hpi:refMonth ?month; hpi:housePriceIndex ?index; hpi:averagePrice ?price .
} ORDER BY DESC(?month) LIMIT 36'''
    raw = request_json("https://landregistry.data.gov.uk/landregistry/query", {"query": query, "format": "json"}, {"Accept": "application/sparql-results+json"})
    bindings = raw.get("results", {}).get("bindings")
    if not isinstance(bindings, list):
        raise ValueError("Unrecognised UK HPI response")
    rows = [{"month": b["month"]["value"][:7], "index": numeric(b["index"]["value"]), "average_price": numeric(b["price"]["value"])} for b in bindings]
    return {"raw": raw, "series": sorted([r for r in rows if r["index"] is not None], key=lambda r:r["month"])}


def gather(inputs, progress=lambda s: None, include_profile=True, public_only=False):
    from .evidence import enriched_inputs, matched_profile, valuation, fallback_title
    from .market_evidence import regional_rent_growth, hydrate_comparables, usable_asking_count
    p = inputs['property']
    if inputs.get('enquiry', {}).get('kind') == 'area':
        raise ValueError('Area enquiries require manual follow-up')
    if not public_only and not os.getenv('PROPERTYDATA_API_KEY'):
        raise ValueError('Add PROPERTYDATA_API_KEY before gathering evidence')
    evidence = {'retrieved_at': now(), 'version': 3, 'sources': [], 'errors': [], 'raw': {}, 'market': {},
                'comparables': [], 'profile': {}, 'hpi': [], 'country_verified': False, 'paid_requests': []}
    try:
        geo = request_json('https://api.postcodes.io/postcodes/' + urllib.parse.quote(p['postcode'], safe=''))
        country = geo.get('result', {}).get('country')
        if country and country != 'England': raise ValueError('V1 only supports England')
        evidence['country_verified'] = country == 'England'
        evidence['location'] = geo.get('result', {})
    except ValueError as exc:
        if 'V1 only' in str(exc): raise
        evidence['errors'].append({'source': 'Postcodes.io', 'message': str(exc)})

    def paid(endpoint, params, reason='Standard research'):
        # Costs listed at request time; actual billing can be lower for incomplete profiles.
        evidence['paid_requests'].append({'endpoint': endpoint, 'budgeted_credits': 20 if endpoint == 'property' else 1,
                                         'params': dict(params), 'reason': reason})
        return pd_call(endpoint, params)

    def collect(name, fn):
        titles = {'property': 'Property facts and sale history', 'rents': 'Local advertised rents',
                  'sold-prices': 'Nearby recorded sales', 'prices-per-sqf': 'Local asking prices by floor area',
                  'sold-prices-per-sqf': 'Local sold prices by floor area', 'growth': 'Local historical price growth',
                  'demand': 'Local sales demand', 'demand-rent': 'Local rental demand',
                  'valuation-sale': 'Property sale valuation', 'valuation-rent': 'Property rental valuation',
                  'build-cost': 'Refurbishment reference estimate', 'hpi': 'England historical house prices',
                  'land-registry': 'Direct Land Registry comparisons', 'land-registry-history': 'Direct Land Registry history',
                  'national-data': 'Regional rental inflation', 'growth-psf': 'Historical sold price per square foot',
                  'prices': 'Additional asking-price comparisons', 'floor-areas': 'Matched floor area',
                  'energy-efficiency': 'Matched EPC', 'title': 'Lease details', 'planning-applications': 'Nearby planning applications'}
        url = 'https://propertydata.co.uk/api/documentation/' + name
        if name.startswith('land-registry'): url = 'https://landregistry.data.gov.uk/app/ppd/'
        if name == 'hpi': url = 'https://landregistry.data.gov.uk/app/ukhpi/'
        src = {'id': name, 'title': titles.get(name, name), 'url': url, 'retrieved_at': now(), 'status': 'ok', 'scope': 'Property / local area'}
        try:
            raw = fn()
            evidence['raw'][name] = raw.get('raw', raw)
            if name == 'property': evidence['profile'] = raw.get('data', {})
            elif name == 'rents':
                d, avg, _ = rent_data(raw)
                if avg is None: raise ValueError('No usable positive area rent returned')
                evidence['market'].update(monthly_rent=avg, rent_sample_size=d.get('points_analysed'), rent_radius=d.get('radius'))
                evidence['comparables'].extend(pd_comparables(raw, 'rent'))
            elif name == 'sold-prices':
                evidence['market']['sold_average'] = numeric(raw.get('data', {}).get('average'))
                evidence['comparables'].extend(pd_comparables(raw, 'sold'))
            elif name in ('prices-per-sqf', 'sold-prices-per-sqf'):
                evidence['market']['asking_price_per_sqft' if name == 'prices-per-sqf' else 'sold_price_per_sqft'] = numeric(raw.get('data', {}).get('average'))
                evidence['comparables'].extend(pd_comparables(raw, 'asking' if name == 'prices-per-sqf' else 'sold', name))
            elif name == 'prices': evidence['comparables'].extend(pd_comparables(raw, 'asking', name))
            elif name == 'national-data':
                evidence['market'][name] = raw  # Keep dataset identity, units and date with values.
                src['scope'] = 'English region; historical annual rental inflation, not a local forecast'
                result = regional_rent_growth(evidence)
                if result['rate'] is None: raise ValueError(result['reason'])
            elif name in ('floor-areas', 'energy-efficiency', 'title'):
                field = {'floor-areas': 'floor_area_sqm', 'energy-efficiency': 'epc_rating', 'title': 'lease_years'}[name]
                src['scope'] = 'Only an unambiguous subject-property match is used'
                value = enriched_inputs(inputs, evidence)['property'].get(field)
                if value in (None, '', 'unknown'):
                    src.update(status='no_data', detail='No unambiguous usable subject match returned')
            elif name == 'land-registry':
                evidence['comparables'].extend(raw['comparables'])
                src['scope'] = 'Same postcode and type; bedroom count and condition unverified'
                if not raw['comparables']: src['status'] = 'no_data'
            elif name == 'land-registry-history':
                evidence['history_candidates'] = raw['comparables']
                src['scope'] = 'Postcode history since 1995; subject identity must match'
                if not raw['comparables']: src['status'] = 'no_data'
            elif name == 'hpi':
                evidence['hpi'] = raw['series']; src['scope'] = 'England; historical context only'
                if not raw['series']: src['status'] = 'no_data'
            elif name.startswith('valuation-'):
                evidence['market'][name] = raw.get('result', raw.get('data', {}))
                # Preserve units from the envelope if the provider returns them there.
                if isinstance(evidence['market'][name], dict) and raw.get('unit'):
                    evidence['market'][name].setdefault('unit', raw['unit'])
                if valuation(evidence, name.split('-')[1]) is None:
                    raise ValueError('No usable valuation returned; rental values require an explicit weekly or monthly unit')
            else: evidence['market'][name] = raw.get('data', raw)
            if name in ('growth', 'growth-psf'): src['scope'] = 'Local series requested for ' + p['postcode'] + '; historical, not a forecast'
            if name == 'planning-applications': src['scope'] = evidence['planning_basis']
            if name == 'build-cost':
                from .finance import refurbishment_estimate
                src['scope'] = evidence['refurbishment_basis']
                if refurbishment_estimate(evidence) is None: raise ValueError('No usable refurbishment cost returned')
            if name == 'property' and not matched_profile({'inputs': inputs, 'evidence': evidence}):
                src['status'] = 'no_data'
                src['detail'] = 'Profile identity could not be matched confidently; facts and history are not used'
                evidence['errors'].append({'source': name, 'message': src['detail']})
        except Exception as exc:
            src['status'] = 'error'
            message = scrub(str(exc)) if isinstance(exc, ValueError) else 'Unexpected response; evidence unavailable'
            evidence['errors'].append({'source': name, 'message': message})
            src['detail'] = message
        evidence['sources'].append(src)
        progress('Researching: ' + src['title'])

    # Resolve the profile first so its verified size/age can feed the valuations.
    if not public_only and include_profile:
        collect('property', lambda: paid('property', {'uprn': p['uprn']} if p.get('uprn') else {'address': p['address'] + ', ' + p['postcode']}))
        evidence['identity_matched'] = bool(matched_profile({'inputs': inputs, 'evidence': evidence}))
    effective = enriched_inputs(inputs, evidence)
    if not public_only:
        # Fill only gaps that remain after the matched profile. These calls are bounded,
        # never fuzzy address matches, and never overwrite supplied property facts.
        for name, field in [('floor-areas', 'floor_area_sqm'), ('energy-efficiency', 'epc_rating')]:
            if effective['property'].get(field) in (None, '', 'unknown'):
                collect(name, lambda n=name: paid(n, {'postcode': p['postcode']}, 'Missing '+field+' after profile'))
        effective = enriched_inputs(inputs, evidence)
        title = fallback_title(effective, evidence)
        if title:
            collect('title', lambda: paid('title', {'title': title}, 'Lease years missing for a single matched leasehold title'))
            effective = enriched_inputs(inputs, evidence)
    p, a = effective['property'], effective['assumptions']
    property_type = api_property_type(p)
    area_params = {'postcode': p['postcode'], 'type': property_type}
    sold_params = dict(area_params, max_age=24)
    if p.get('new_build'): sold_params['class'] = 'new_build'
    if p['tenure'] in ('freehold', 'leasehold'): sold_params['tenure'] = p['tenure']
    size_params = {}
    if p.get('floor_area_sqm'):
        sqft = p['floor_area_sqm'] * 10.7639104167
        size_params = {'min_sqf': max(1, math.floor(sqft * .75)), 'max_sqf': math.ceil(sqft * 1.25)}
    tasks = [('land-registry', lambda: land_registry(p['postcode'], property_type)),
             ('land-registry-history', lambda: land_registry(p['postcode'], property_type, history=True)), ('hpi', hpi)]
    if not public_only:
        for name, params in [
            ('rents', dict(area_params, bedrooms=p['bedrooms'])),
            ('sold-prices', sold_params),
            ('prices-per-sqf', dict(area_params, **size_params)), ('growth', {'postcode': p['postcode']}),
            ('growth-psf', {'postcode': p['postcode']}),
            ('national-data', {'dataset': 'rent-inflation-by-english-region'}),
            ('demand', {'postcode': p['postcode']}), ('demand-rent', {'postcode': p['postcode']}),
            ('sold-prices-per-sqf', dict(sold_params, **size_params))]:
            tasks.append((name, lambda n=name, q=params: paid(n, q)))
        if a.get('refurbishment_planned') or (a.get('refurbishment') or 0) > 0:
            params = {'postcode': p['postcode'], 'results': 10, 'max_radius': .25, 'max_age': 1095}
            identity = matched_profile({'inputs': effective, 'evidence': evidence}).get('identity', {})
            if numeric(identity.get('lat')) is not None and numeric(identity.get('lng')) is not None:
                params.pop('postcode'); params['location'] = str(identity['lat'])+','+str(identity['lng'])
            evidence['planning_basis'] = 'Up to 10 applications within 0.25 miles of '+('the matched property' if 'location' in params else 'the postcode centre')+' in the last 3 years; default application types, all decisions. Not a complete planning search or permission for proposed work.'
            tasks.append(('planning-applications', lambda q=params: paid('planning-applications', q, 'Refurbishment is planned')))
        required = ('construction_date', 'finish_quality', 'outdoor_space', 'floor_area_sqm', 'bathrooms', 'off_street_parking')
        if all(p.get(k) is not None and p.get(k) != '' for k in required) and p['floor_area_sqm'] * 10.7639104167 >= 300:
            params = {k:p[k] for k in ('postcode', 'construction_date', 'finish_quality', 'outdoor_space', 'bedrooms', 'bathrooms', 'off_street_parking')}
            params.update(property_type=property_type, internal_area=round(p['floor_area_sqm'] * 10.7639104167))
            for name in ('valuation-sale', 'valuation-rent'): tasks.append((name, lambda n=name, q=params: paid(n, q)))
        else:
            evidence['valuation_note'] = 'Property valuation unavailable: size, age, condition, bathrooms, outdoor space and parking are required; minimum area 300 sqft.'
            for name in ('valuation-sale', 'valuation-rent'):
                evidence['errors'].append({'source': name, 'message': evidence['valuation_note']})
        evidence['refurbishment_basis'] = a['refurb_level'].replace('refurb_', '') + ' refurbishment; ' + a['refurb_finish'] + ' finish; ' + str(p.get('floor_area_sqm')) + ' sqm. Reference estimate, not a contractor quote.'
        if p.get('floor_area_sqm') and p['floor_area_sqm'] * 10.7639104167 >= 600:
            params = {'postcode': p['postcode'], 'internal_area': round(p['floor_area_sqm']*10.7639104167), 'project_type': a['refurb_level'], 'finish_quality': a['refurb_finish']}
            tasks.append(('build-cost', lambda q=params: paid('build-cost', q)))
        else:
            evidence['errors'].append({'source': 'build-cost', 'message': 'Refurbishment estimate requires a known area of at least 600 sqft; no area was inflated to obtain an estimate.'})
    else:
        evidence['errors'].append({'source': 'PropertyData', 'message': 'Not configured; property valuations and area rents unavailable.'})
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(collect, name, fn) for name, fn in tasks]
        for future in futures: future.result()
    hydrate_comparables(evidence)
    if not public_only and usable_asking_count(effective, evidence) < 3:
        collect('prices', lambda: paid('prices', dict(area_params, bedrooms=p['bedrooms']), 'Fewer than three usable asking-price candidates'))
        hydrate_comparables(evidence)
    evidence['sources'].sort(key=lambda s:s['id'])
    evidence['budgeted_credits'] = sum(r['budgeted_credits'] for r in evidence['paid_requests'])
    return evidence
