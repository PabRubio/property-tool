"""Dated comparison selection; a nearby listing is not automatically a match."""
import calendar
from datetime import date
from statistics import median
from .schema import api_property_type
from .evidence import address_key


def months_ago(months, today=None):
    today = today or date.today()
    year, month = divmod(today.year * 12 + today.month - 1 - months, 12)
    return date(year, month + 1, min(today.day, calendar.monthrange(year, month + 1)[1]))


def recent_sale(row):
    try: return months_ago(18) <= date.fromisoformat(str(row.get('date', ''))[:10]) <= date.today()
    except ValueError: return False


def assess(row, property_, kind):
    reasons = []
    if not row.get('source_url'): reasons.append('No source link')
    if row.get('bedrooms') != property_['bedrooms']: reasons.append('Bedroom count differs or is unknown')
    if row.get('property_type') != api_property_type(property_): reasons.append('Property type differs or is unknown')
    same_postcode = address_key(row.get('postcode') or '') == address_key(property_['postcode'])
    if row.get('distance') is None and not same_postcode or row.get('distance') is not None and not 0 < row['distance'] <= 1: reasons.append('Distance unverified or beyond one mile')
    if address_key(row.get('address', ''), row.get('postcode', '')) in {address_key(property_['address']), address_key(property_['address'], property_['postcode'])}:
        reasons.append('Subject property, not an independent comparison')
    if kind == 'sold':
        if not recent_sale(row): reasons.append('Sale outside the last 18 months or undated')
        area, subject = row.get('floor_area_sqm'), property_.get('floor_area_sqm')
        if not area or not subject or not .75 <= area / subject <= 1.25: reasons.append('Floor area differs or is unverified')
        if property_['tenure'] != 'unknown' and row.get('tenure') != property_['tenure']: reasons.append('Tenure differs or is unknown')
        if property_.get('new_build') and row.get('transaction_class') != 'new_build': reasons.append('New-build transaction status differs or is unknown')
    else:
        try: age = (date.today() - date.fromisoformat(str(row.get('observed_at') or row.get('date') or '')[:10])).days
        except ValueError: age = 999
        if not 0 <= age <= 90: reasons.append(('Rental' if kind == 'rent' else 'For-sale')+' listing is undated or over 90 days old')
        # PD's monthly sample is a whole-property asking-rent dataset. Web evidence
        # must explicitly establish this: per-room student/HMO adverts cannot substitute.
        if kind == 'rent' and row.get('source_id', '').startswith('research-') and row.get('rental_basis') != 'whole_property_monthly':
            reasons.append('Whole-property monthly rent not established')
        area, subject = row.get('floor_area_sqm'), property_.get('floor_area_sqm')
        if area and subject and not .75 <= area / subject <= 1.25: reasons.append('Floor area differs materially')
        if kind == 'asking' and property_['tenure'] != 'unknown' and row.get('tenure') != property_['tenure']:
            reasons.append('Tenure differs or is unknown')
    return reasons


def comparison_summary(inputs, evidence, kind):
    rows = [dict(c) for c in evidence.get('comparables', []) if c.get('kind') == kind]
    rows += [dict(c, source_id='comparable-'+str(i+1)) for i,c in enumerate(inputs.get('comparables', [])) if c.get('selected') and c.get('kind') == kind]
    if kind == 'sold': rows = [r for r in rows if recent_sale(r)]
    unique = {}
    for row in rows:
        if not isinstance(row.get('amount'), (int, float)) or row['amount'] <= 0: continue
        key = address_key(row.get('address', ''), row.get('postcode') or '')
        if not key: continue
        row['limitations'] = assess(row, inputs['property'], kind)
        old = unique.get(key)
        if old is None or len(row['limitations']) < len(old['limitations']): unique[key] = row
    def rank(row):
        subject = inputs['property'].get('floor_area_sqm')
        area_gap = abs(row['floor_area_sqm']/subject-1) if row.get('floor_area_sqm') and subject else 999
        try: recency = date.fromisoformat(str(row.get('date') if kind=='sold' else row.get('observed_at') or '')[:10]).toordinal()
        except ValueError: recency = 0
        return (len(row['limitations']), row.get('distance') if row.get('distance') is not None else 999, area_gap, -recency, row['address'])
    rows = sorted(unique.values(), key=rank)
    matched = [r for r in rows if not r['limitations']]
    enough = len(matched) >= 3
    values = [r['amount'] for r in matched]
    return {'kind': kind, 'candidates': rows, 'matched': matched, 'count': len(matched),
            'range': [min(values), max(values)] if enough else None,
            'median': median(values) if enough else None,
            'basis': 'Unadjusted range and median of at least three distinct, dated, type/bedroom/location-compatible '+({'sold':'sales within 18 months, with matching tenure and size.', 'rent':'whole-property asking rents observed within 90 days; not achieved rents. Condition and letting terms still require review.', 'asking':'asking-price listings observed within 90 days; not completed sale prices. Condition, size and terms still require review.'}[kind]),
            'reason': None if enough else 'Fewer than three sufficiently matched, independently sourced comparisons; no evidence-supported range established.'}
