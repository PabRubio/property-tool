"""Conservative property identity checks for report facts and sale history."""
import re
from .providers import numeric
from .schema import iso_date


def address_key(address, postcode=''):
    key = re.sub(r'[^A-Z0-9]', '', str(address).upper())
    pc = re.sub(r'[^A-Z0-9]', '', postcode.upper())
    return key if not pc or key.endswith(pc) else key + pc


def matched_profile(record):
    p = record['inputs']['property']
    profile = record['evidence'].get('profile', {})
    identity = profile.get('identity', {})
    if identity.get('data_status') != 'found':
        return {}
    if p.get('uprn'):
        return profile if str(identity.get('uprn', '')) == p['uprn'] else {}
    if identity.get('address') and address_key(identity['address']) == address_key(p['address'], p['postcode']):
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
            rows.append(dict(c, source_id='land-registry-history' if c.get('source', '').startswith('HM Land') else 'inputs'))
    profile = matched_profile(record)
    sales = profile.get('sales', {})
    if sales.get('data_status') == 'found':
        for tx in sales.get('transactions', []):
            txid = str(tx.get('transaction_id', ''))
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
