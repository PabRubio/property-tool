import concurrent.futures
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, date, timedelta, timezone


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
    if unit in ("week", "weekly", "pw", "per week", "gbp/week", "£pw", "£ per week"):
        multiplier = 52 / 12
    elif unit in ("month", "monthly", "pcm", "per month", "gbp/month", "£pcm", "£ per month"):
        multiplier = 1
    else:
        raise ValueError("Unrecognised rent unit; inspect raw data before using it")
    avg = numeric(d.get("average"))
    return d, round(avg * multiplier, 2) if avg is not None and avg > 0 else None, multiplier


def pd_comparables(raw, kind):
    d, multiplier = raw.get("data", {}), 1
    if kind == "rent":
        d, _, multiplier = rent_data(raw)
    rows = []
    for c in d.get("raw_data", [])[:60]:
        amount = numeric(c.get("price"))
        if not amount or amount <= 0 or not c.get("address"):
            continue
        sqm = numeric(c.get("sqf"))
        rows.append({"kind": kind, "address": str(c["address"]), "amount": round(amount * multiplier, 2),
                     "date": str(c.get("date", ""))[:10], "source_url": str(c.get("url", "")),
                     "bedrooms": numeric(c.get("bedrooms")), "floor_area_sqm": round(sqm / 10.7639104167, 2) if sqm else None,
                     "selected": False, "source": "PropertyData / " + ("Land Registry" if kind == "sold" else "advertised rent"),
                     "property_type": str(c.get("type", "")),
                     "notes": "Distance reported: %s. %s" % (c.get("distance", "unknown"), "Confirm property match and date." if kind == "sold" else "Advertised rent, not verified achieved rent. Checked " + date.today().isoformat())})
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
    p = inputs["property"]
    if not public_only and not os.getenv("PROPERTYDATA_API_KEY"):
        raise ValueError("Add PROPERTYDATA_API_KEY to .env and restart before gathering live evidence")
    evidence = {"retrieved_at": now(), "sources": [], "errors": [], "raw": {}, "market": {}, "comparables": [], "profile": {}, "hpi": [], "country_verified": False}
    # Verify jurisdiction before spending PropertyData credits when lookup succeeds.
    try:
        geo = request_json("https://api.postcodes.io/postcodes/" + urllib.parse.quote(p["postcode"], safe=""))
        country = geo.get("result", {}).get("country")
        if country and country != "England":
            raise ValueError("This postcode is in %s. V1 only supports England." % country)
        evidence["country_verified"] = country == "England"
        evidence["location"] = geo.get("result", {})
    except ValueError as e:
        if "V1 only" in str(e):
            raise
        evidence["errors"].append({"source": "Postcodes.io", "message": str(e)})
    tasks = [("rents", lambda: pd_call("rents", {"postcode": p["postcode"], "bedrooms": p["bedrooms"], "type": p["property_type"]})),
             ("sold-prices", lambda: pd_call("sold-prices", {"postcode": p["postcode"], "type": p["property_type"], "max_age": 24})),
             ("prices-per-sqf", lambda: pd_call("prices-per-sqf", {"postcode": p["postcode"]})),
             ("growth", lambda: pd_call("growth", {"postcode": p["postcode"]})),
             ("demand", lambda: pd_call("demand", {"postcode": p["postcode"]})),
             ("land-registry", lambda: land_registry(p["postcode"], p["property_type"])),
             ("hpi", hpi)]
    if include_profile:
        tasks.append(("property", lambda: pd_call("property", {"uprn": p["uprn"]} if p["uprn"] else {"address": p["address"] + ", " + p["postcode"]})))
    else:
        tasks.append(("energy-efficiency", lambda: pd_call("energy-efficiency", {"postcode": p["postcode"]})))
    required_avm = ("construction_date", "finish_quality", "outdoor_space", "floor_area_sqm", "bathrooms", "off_street_parking")
    if all(p.get(k) is not None and p.get(k) != "" for k in required_avm) and p["floor_area_sqm"] * 10.7639104167 >= 300:
        params = {k:p[k] for k in ("postcode", "property_type", "construction_date", "finish_quality", "outdoor_space", "bedrooms", "bathrooms", "off_street_parking")}
        params["internal_area"] = round(p["floor_area_sqm"] * 10.7639104167)
        for endpoint in ("valuation-sale", "valuation-rent"):
            tasks.append((endpoint, lambda e=endpoint: pd_call(e, params)))
    else:
        evidence["valuation_note"] = "AVM cross-check skipped: complete age, finish, area (at least 300 sqft), bathrooms, outdoor space and parking to enable it. No missing attributes were guessed."
    tasks.append(("land-registry-history", lambda: land_registry(p["postcode"], p["property_type"], history=True)))
    if public_only:
        tasks = [(name, fn) for name, fn in tasks if name in ("land-registry", "land-registry-history", "hpi")]
        evidence["errors"].append({"source": "PropertyData", "message": "API key not configured. Area rents and property profile are unavailable; supply a rent estimate to calculate returns."})
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(fn): name for name, fn in tasks}
        done = 0
        for f in concurrent.futures.as_completed(futures):
            name = futures[f]
            source_url = "https://propertydata.co.uk/api/documentation/" + name
            if name.startswith("land-registry"): source_url = "https://landregistry.data.gov.uk/app/ppd/"
            if name == "hpi": source_url = "https://landregistry.data.gov.uk/app/ukhpi/"
            src = {"id": name, "title": name.replace("-", " "), "url": source_url, "retrieved_at": now(), "status": "ok", "scope": "Property / local area"}
            try:
                raw = f.result()
                evidence["raw"][name] = raw.get("raw", raw)
                if name == "rents":
                    d, avg, _ = rent_data(raw)
                    evidence["market"].update(monthly_rent=avg, rent_sample_size=d.get("points_analysed"), rent_radius=d.get("radius"))
                    evidence["comparables"].extend(pd_comparables(raw, "rent"))
                    if avg is None: raise ValueError("No usable positive area rent returned")
                elif name == "sold-prices":
                    evidence["market"]["sold_average"] = numeric(raw.get("data", {}).get("average"))
                    evidence["comparables"].extend(pd_comparables(raw, "sold"))
                elif name == "prices-per-sqf":
                    evidence["market"]["asking_price_per_sqft"] = numeric(raw.get("data", {}).get("average"))
                elif name == "land-registry":
                    evidence["comparables"][0:0] = raw["comparables"]
                    src["scope"] = "Exact postcode, same type, standard transactions, last 24 months; no bedroom/size match"
                    if not raw["comparables"]: src["status"] = "no_data"
                elif name == "land-registry-history":
                    evidence["history_candidates"] = raw["comparables"]
                    src["scope"] = "Postcode and property type since 1995, newest 200 standard transactions; exact address match required for subject history"
                    if not raw["comparables"]: src["status"] = "no_data"
                elif name == "hpi":
                    evidence["hpi"] = raw["series"]
                    src["scope"] = "England, all residential property; historical context only"
                    if not raw["series"]: src["status"] = "no_data"
                elif name == "property":
                    evidence["profile"] = raw.get("data", {})
                elif name.startswith("valuation-"):
                    evidence["market"][name] = raw.get("result", {})
                else:
                    evidence["market"][name] = raw.get("data", raw)
            except Exception as e:
                src["status"] = "error"
                message = scrub(str(e)) if isinstance(e, ValueError) else "Unexpected provider response; inspect returned data"
                evidence["errors"].append({"source": name, "message": message})
            evidence["sources"].append(src)
            done += 1
            progress("Gathered %s/%s sources: %s" % (done, len(tasks), name))
    # Prefer directly sourced Land Registry rows when identical transactions recur.
    seen, unique = set(), []
    for c in sorted(evidence["comparables"], key=lambda x: 0 if x["source"].startswith("HM Land") else 1):
        key = (c["kind"], re.sub(r"[^A-Z0-9]", "", c["address"].upper()), c["amount"], c["date"])
        if key not in seen:
            seen.add(key); unique.append(c)
    evidence["comparables"] = unique
    return evidence
