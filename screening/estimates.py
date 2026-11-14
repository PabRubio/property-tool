"""Labelled AI valuation scenarios, kept separate from inputs and PropertyData."""
import hashlib
import json
import math
from datetime import date, datetime, timezone

from .comparisons import comparison_summary, rent_basis
from .evidence import address_key, enriched_inputs
from .providers import now
from .commercial import is_commercial


def fingerprint(inputs, evidence):
    property_ = enriched_inputs(inputs, evidence)['property']
    return hashlib.sha256(json.dumps(property_, sort_keys=True).encode()).hexdigest()


def candidates(record):
    """Expose identifiable, dated observations; imperfect matches remain eligible.

    The existing strict matched medians are unchanged. Codex must explain any
    adjustments for bedrooms, size, condition, tenure and asking versus sold.
    """
    inputs, evidence = record['inputs'], record['evidence']
    sources = {s['id'] for s in evidence.get('sources', []) if s.get('status') == 'ok'}
    sources.update('comparable-%s' % (i + 1) for i, c in enumerate(inputs.get('comparables', [])) if c.get('selected'))
    result = []
    for kind in ('rent', 'sold', 'asking'):
        for row in comparison_summary(inputs, evidence, kind)['candidates']:
            refs = row.get('source_ids') or [row.get('source_id')]
            if not refs or any(s not in sources for s in refs) or not row.get('source_url'):
                continue
            try:
                observed = date.fromisoformat(str(row.get('date') if kind == 'sold' else row.get('observed_at') or '')[:10])
            except ValueError:
                continue
            if kind != 'sold' and not 0 <= (date.today() - observed).days <= 90:
                continue
            commercial = is_commercial(inputs)
            if commercial and (row.get('property_type') != inputs['property']['property_type'] or
                               row.get('floor_area_basis') != inputs['property'].get('floor_area_basis') or
                               row.get('floor_area_basis') not in ('gia', 'nia')):
                continue
            expected_basis = 'commercial_unit_monthly' if commercial else 'whole_property_monthly'
            if kind == 'rent' and (rent_basis(row).startswith(('Per room', 'Student')) or
                                   row.get('rental_basis') != expected_basis and (commercial or row.get('source_id') != 'rents')):
                continue
            subject = inputs['property']
            postcode = address_key(row.get('postcode') or '')
            district = subject['postcode'].split(' ')[0].upper()
            nearby = postcode and postcode.startswith(address_key(district))
            distance = row.get('distance')
            if not nearby and not (isinstance(distance, (int, float)) and 0 < distance <= 3):
                continue
            if address_key(row['address']) in (address_key(subject['address']), address_key(subject['address'], subject['postcode'])):
                continue
            identity = {key: row.get(key) for key in ('kind', 'address', 'postcode', 'amount', 'date', 'observed_at',
                        'source_url', 'bedrooms', 'floor_area_sqm', 'property_type', 'tenure', 'distance',
                        'rental_basis', 'notes', 'condition', 'finish_quality', 'transaction_class', 'evidence_quote', 'floor_area_basis', 'lease_terms')}
            identity['source_ids'] = refs
            result.append(dict(row, id='candidate-' + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:12], source_ids=refs))
    return result


def apply(record, proposed):
    rows = {row['id']: row for row in candidates(record)}
    accepted = {}
    for estimate in proposed if isinstance(proposed, list) else []:
        if not isinstance(estimate, dict) or estimate.get('kind') not in ('rent', 'sale'):
            continue
        kind = estimate['kind']
        numbers = [estimate.get(key) for key in ('low', 'estimate', 'high')]
        ceiling = 100000 if kind == 'rent' else 100000000
        if any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or not 0 < n <= ceiling for n in numbers):
            continue
        if not numbers[0] <= numbers[1] <= numbers[2] or numbers[0] == numbers[2]:
            continue
        ids = estimate.get('comparable_ids', [])
        if not isinstance(ids, list) or any(not isinstance(i, str) or i not in rows for i in ids):
            continue
        used = [rows[i] for i in ids]
        if len({address_key(row['address']) for row in used}) < 2:
            continue
        if any(row['kind'] not in (('rent',) if kind == 'rent' else ('sold', 'asking')) for row in used):
            continue
        if any(not isinstance(estimate.get(key), str) or not 1 <= len(estimate[key].strip()) <= limit
               for key, limit in (('basis', 600), ('limitations', 400))):
            continue
        accepted[kind] = dict(estimate, source_ids=sorted({s for row in used for s in row['source_ids']}),
                              fingerprint=fingerprint(record['inputs'], record['evidence']), generated_at=now(),
                              unit='GBP_per_month' if kind == 'rent' else 'GBP', provider='codex',
                              comparables=used)
    record['evidence'].setdefault('estimates', {}).update(accepted)
    return accepted


def get(inputs, evidence, kind):
    estimate = evidence.get('estimates', {}).get(kind)
    if not estimate or estimate.get('fingerprint') != fingerprint(inputs, evidence):
        return None
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(estimate['generated_at'])).total_seconds()
    except (KeyError, ValueError, TypeError):
        return None
    if not 0 <= age < 30 * 86400:
        return None
    # Revalidate against today's evidence: removed or expired comparisons invalidate it.
    check = {'inputs': inputs, 'evidence': dict(evidence, estimates={})}
    return apply(check, [estimate]).get(kind)


def basis(estimate):
    unit = '/month' if estimate['kind'] == 'rent' else ''
    refs = ', '.join(estimate['source_ids'])
    return ('Analyst estimate £{:,.0f}{}; indicative range £{:,.0f}–£{:,.0f}{}. '
            'Evidence-adjusted scenario, subject to analyst review [{}].').format(
                estimate['estimate'], unit, estimate['low'], estimate['high'], unit, refs)
