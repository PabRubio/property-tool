import math
import re
from datetime import date
from urllib.parse import urlsplit


# Each numeric field is defined once for browser controls and server validation.
FIELDS = [
    ("purchase_price", "Agreed / proposed purchase price (£)", "Acquisition", None, 1, 100000000),
    ("monthly_rent", "Selected monthly rent (£)", "Rent & running costs", None, 1, 1000000),
    ("refurbishment", "Refurbishment budget (£)", "Acquisition", 0, 0, 10000000),
    ("contingency_pct", "Refurbishment contingency (%)", "Acquisition", 10, 0, 100),
    ("legal_fees", "Legal costs including VAT (£)", "Acquisition", 2000, 0, 1000000),
    ("survey_fees", "Survey costs (£)", "Acquisition", 600, 0, 100000),
    ("mortgage_fees", "Mortgage / broker fees paid upfront (£)", "Acquisition", 0, 0, 1000000),
    ("other_purchase_costs", "Other purchase costs (£)", "Acquisition", 0, 0, 1000000),
    ("cash_reserve", "Cash buffer held aside (£)", "Acquisition", 3000, 0, 10000000),
    ("sdlt_override", "Adviser-supplied total purchase tax (£; optional)", "Acquisition", None, 0, 10000000),
    ("ltv_pct", "Mortgage as % of purchase price", "Finance", 75, 0, 95),
    ("interest_rate_pct", "Annual mortgage interest rate (%)", "Finance", 5.5, 0, 30),
    ("mortgage_term_years", "Mortgage term (years)", "Finance", 25, 1, 40),
    ("void_pct", "Ongoing rent lost to vacancies / arrears (%)", "Rent & running costs", 5, 0, 100),
    ("initial_void_months", "Initial whole months without rent", "Rent & running costs", 0, 0, 24),
    ("management_pct", "Management fee incl. VAT (% of collected rent)", "Rent & running costs", 12, 0, 50),
    ("maintenance_pct", "Maintenance allowance (% of scheduled rent)", "Rent & running costs", 5, 0, 50),
    ("service_charge", "Annual service charge (£; blank = unknown)", "Rent & running costs", None, 0, 1000000),
    ("ground_rent", "Annual ground rent (£; blank = unknown)", "Rent & running costs", None, 0, 1000000),
    ("insurance", "Annual landlord insurance (£)", "Rent & running costs", 350, 0, 100000),
    ("compliance", "Annual safety / compliance budget (£)", "Rent & running costs", 250, 0, 100000),
    ("letting_fees", "Annual letting / renewal fees incl. VAT (£)", "Rent & running costs", 300, 0, 100000),
    ("other_annual_costs", "Other annual costs / major works reserve (£)", "Rent & running costs", 0, 0, 1000000),
    ("void_cost_monthly", "Council tax / utilities per empty month (£)", "Rent & running costs", 200, 0, 100000),
    ("annual_tax_budget", "Adviser-supplied annual income tax (£; optional)", "Tax & exit", None, 0, 10000000),
    ("sale_tax_budget", "Adviser-supplied tax on sale (£; optional)", "Tax & exit", None, 0, 10000000),
    ("holding_years", "Holding period (years)", "Tax & exit", 5, 1, 30),
    ("rent_growth_pct", "Assumed annual rent change (%)", "Tax & exit", 0, -20, 20),
    ("cost_growth_pct", "Assumed annual cost change (%)", "Tax & exit", 2, -20, 30),
    ("price_growth_pct", "Assumed annual property price change (%)", "Tax & exit", 0, -20, 20),
    ("selling_fee_pct", "Selling agent fee incl. VAT (%)", "Tax & exit", 1.5, 0, 20),
    ("sale_legal_fees", "Legal fees on sale (£)", "Tax & exit", 1500, 0, 1000000),
    ("early_repayment_fee", "Mortgage early repayment charge on sale (£)", "Tax & exit", 0, 0, 1000000),
    ("min_net_yield_pct", "Target net yield on total property cost (%)", "Screening targets", 4, 0, 100),
    ("min_monthly_cashflow", "Target monthly cash flow before income tax (£)", "Screening targets", 100, -100000, 1000000),
    ("rent_stress_pct", "Stress scenario: rent reduction (%)", "Screening targets", 10, 0, 100),
    ("rate_stress_pp", "Stress scenario: interest rise (percentage points)", "Screening targets", 2, 0, 20),
    ("cost_stress_pct", "Stress scenario: running-cost increase (%)", "Screening targets", 20, 0, 200),
]
INT_FIELDS = {"mortgage_term_years", "initial_void_months", "holding_years"}
PROPERTY_TYPES = ["flat", "terraced_house", "semi-detached_house", "detached_house"]


def defaults():
    return {"investor": {"name": "", "email": "", "cash_budget": None, "goal": "Balanced income and risk", "risk_tolerance": "moderate", "notes": ""},
            "property": {"address": "", "postcode": "", "country": "England", "asking_price": None,
                         "listing_url": "", "listing_checked": "", "property_type": "flat",
                         "bedrooms": 2, "floor_area_sqm": None, "tenure": "unknown", "lease_years": None,
                         "epc_rating": "unknown", "cladding_status": "unknown", "listing_notes": "", "uprn": "",
                         "construction_date": "", "finish_quality": "", "outdoor_space": "", "bathrooms": None, "off_street_parking": None},
            "assumptions": dict({f[0]: f[3] for f in FIELDS}, financing="interest_only", buyer_type="individual",
                                additional_property=True, nonresident=False, corporate_relief_confirmed=False,
                                new_lease=False, rent_source="", cost_source="", finance_source="", tax_source=""),
            "comparables": [], "analyst_notes": "", "input_provenance": {}}


def number(v, label, low=0, high=100000000, optional=True):
    if v is None or v == "":
        if optional:
            return None
        raise ValueError(label + " is required")
    if isinstance(v, bool):
        raise ValueError(label + " must be a number")
    try:
        n = float(v)
    except (ValueError, TypeError):
        raise ValueError(label + " must be a number")
    if not math.isfinite(n) or not low <= n <= high:
        raise ValueError("%s must be between %s and %s" % (label, low, high))
    return n


def string(v, label, limit=8000):
    if not isinstance(v, str) or len(v) > limit:
        raise ValueError(label + " must be text (maximum %s characters)" % limit)
    return v.strip()


def url(v):
    v = string(v or "", "Source URL", 2000)
    if v and (urlsplit(v).scheme not in ("http", "https") or not urlsplit(v).netloc):
        raise ValueError("Links must be http or https URLs")
    return v


def iso_date(v, label, optional=True):
    if not v and optional:
        return ""
    try:
        d = date.fromisoformat(v)
    except (TypeError, ValueError):
        raise ValueError(label + " must be YYYY-MM-DD")
    if d > date.today():
        raise ValueError(label + " cannot be in the future")
    return d.isoformat()


def validate(payload):
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object")
    out = defaults()
    for group in ("investor", "property", "assumptions"):
        obj = payload.get(group, {})
        if not isinstance(obj, dict):
            raise ValueError(group + " must be an object")
        for key in out[group]:
            if key in obj:
                out[group][key] = obj[key]
    i, p, a = out["investor"], out["property"], out["assumptions"]
    for key,limit in (("name",150),("email",254),("goal",500),("risk_tolerance",20),("notes",8000)):
        i[key] = string(i[key], key,limit)
    if i["risk_tolerance"] not in ("low","moderate","high"):
        raise ValueError("Invalid risk tolerance")
    i["cash_budget"] = number(i["cash_budget"], "Available cash")
    for key in ("address", "postcode", "country", "property_type", "tenure", "epc_rating", "cladding_status", "listing_notes", "uprn", "construction_date", "finish_quality", "outdoor_space"):
        p[key] = string(p[key], key)
    if not p["address"]:
        raise ValueError("Property address is required")
    if len(p["address"]) > 500:
        raise ValueError("Property address must be under 500 characters")
    pc = re.sub(r"\s+", "", p["postcode"].upper())
    if not re.fullmatch(r"[A-Z]{1,2}[0-9][A-Z0-9]?[0-9][A-Z]{2}", pc):
        raise ValueError("Enter a full UK postcode")
    p["postcode"] = pc[:-3] + " " + pc[-3:]
    if p["country"] != "England":
        raise ValueError("V1 supports England only")
    if p["property_type"] not in PROPERTY_TYPES or p["tenure"] not in ("freehold", "leasehold", "unknown"):
        raise ValueError("Invalid property type or tenure")
    if p["epc_rating"] not in list("ABCDEFG") + ["unknown"]:
        raise ValueError("Invalid EPC rating")
    if p["cladding_status"] not in ("unknown", "not_applicable", "evidence_reviewed", "concern"):
        raise ValueError("Invalid building safety status")
    p["listing_url"] = url(p["listing_url"])
    p["listing_checked"] = iso_date(p["listing_checked"], "Listing checked date")
    p["asking_price"] = number(p["asking_price"], "Asking price", 1, optional=False)
    p["floor_area_sqm"] = number(p["floor_area_sqm"], "Floor area", 1, 10000)
    p["lease_years"] = number(p["lease_years"], "Lease years", 0, 999)
    p["bedrooms"] = number(p["bedrooms"], "Bedrooms", 0, 5, False)
    if p["bedrooms"] % 1:
        raise ValueError("Bedrooms must be a whole number")
    p["bedrooms"] = int(p["bedrooms"])
    for key, maximum in (("bathrooms", 5), ("off_street_parking", 3)):
        p[key] = number(p[key], key, 0, maximum)
        if p[key] is not None and p[key] % 1:
            raise ValueError(key + " must be a whole number")
    for key, choices in (("construction_date", ["", "pre_1914", "1914_2000", "2000_onwards"]), ("finish_quality", ["", "very_high", "high", "average", "below_average", "unmodernised"]), ("outdoor_space", ["", "none", "balcony_terrace", "garden", "garden_very_large"])):
        if p[key] not in choices:
            raise ValueError("Invalid " + key)
    if p["uprn"] and not re.fullmatch(r"\d{1,12}", p["uprn"]):
        raise ValueError("UPRN must contain up to 12 digits")
    for key, label, _, default, low, high in FIELDS:
        a[key] = number(a[key], label, low, high, default is None)
        if key in INT_FIELDS:
            if a[key] % 1:
                raise ValueError(label + " must be a whole number")
            a[key] = int(a[key])
    for key in ("additional_property", "nonresident", "corporate_relief_confirmed", "new_lease"):
        if not isinstance(a[key], bool):
            raise ValueError(key + " must be true or false")
    for key in ("rent_source", "cost_source", "finance_source", "tax_source"):
        a[key] = string(a[key], key)
    if a["financing"] not in ("cash", "interest_only", "repayment") or a["buyer_type"] not in ("individual", "company"):
        raise ValueError("Invalid finance or buyer type")
    if a["holding_years"] > a["mortgage_term_years"] and a["financing"] == "interest_only":
        raise ValueError("Holding period cannot exceed the interest-only mortgage term; model refinancing separately")
    comps = payload.get("comparables", [])
    if not isinstance(comps, list) or len(comps) > 100:
        raise ValueError("Provide at most 100 comparables")
    for c in comps:
        if not isinstance(c, dict) or c.get("kind") not in ("sold", "rent"):
            raise ValueError("Each comparable needs kind sold or rent")
        row = {"kind": c["kind"], "address": string(c.get("address", ""), "Comparable address", 500),
               "amount": number(c.get("amount"), "Comparable price / monthly rent", 1, optional=False),
               "date": iso_date(c.get("date", ""), "Comparable date"), "source_url": url(c.get("source_url", "")),
               "notes": string(c.get("notes", ""), "Comparable notes", 2000),
               "bedrooms": number(c.get("bedrooms"), "Comparable bedrooms", 0, 20),
               "floor_area_sqm": number(c.get("floor_area_sqm"), "Comparable floor area", 1, 10000),
               "selected": c.get("selected", False), "source": string(c.get("source", "Analyst supplied"), "Source", 200),
               "property_type": string(c.get("property_type", ""), "Comparable type", 100)}
        if not row["address"] or not isinstance(row["selected"], bool):
            raise ValueError("Comparables need an address and selected true/false")
        out["comparables"].append(row)
    out["analyst_notes"] = string(payload.get("analyst_notes", ""), "Analyst notes")
    return out
