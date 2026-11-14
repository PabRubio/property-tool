"""Commercial PropertyData requests; residential datasets are never substitutes."""
from .commercial import area_basis, valuation_area_ready


def gather_market(inputs, evidence, paid, progress, public_only=False):
    from .providers import now, numeric, scrub
    p, a = inputs['property'], inputs['assumptions']
    evidence['asset_class'] = 'commercial'
    evidence['refurbishment_basis'] = 'Commercial works require a supplied contractor budget; residential build-cost estimates are not used.'
    if public_only:
        evidence['errors'].append({'source': 'PropertyData', 'message': 'Not configured; commercial valuations unavailable.'})
        return evidence
    tasks = [('rents-commercial', {'postcode': p['postcode'], 'type': p['property_type']},
              'Local commercial quoting rents; annual area context, not a subject valuation')]
    if valuation_area_ready(p):
        params = {'postcode': p['postcode'], 'property_type': p['property_type'],
                  'internal_area': p['floor_area_sqm'], 'area_unit': 'sqm'}
        tasks.extend((name, params, scope) for name, scope in [
            ('valuation-commercial-rent', 'Indicative annual commercial asking rent; not a confirmed lease'),
            ('valuation-commercial-sale', 'Indicative capital value from quoting rents and standard capitalisation rates; not completed sales')])
    else:
        evidence['valuation_note'] = 'Commercial valuation needs a known floor area measured as ' + area_basis(p).upper() + '.'
        evidence['errors'].append({'source': 'commercial-valuations', 'message': evidence['valuation_note']})
    if a.get('refurb_level') != 'none':
        evidence['planning_basis'] = 'Nearby applications within 0.25 miles of the postcode centre over three years; not confirmation of subject consent or permitted use.'
        tasks.append(('planning-applications', {'postcode': p['postcode'], 'results': 10, 'max_radius': .25, 'max_age': 1095}, evidence['planning_basis']))
    for name, params, scope in tasks:
        source = {'id': name, 'title': name.replace('-', ' ').capitalize(),
                  'url': 'https://propertydata.co.uk/api/documentation/' + name,
                  'retrieved_at': now(), 'status': 'ok', 'scope': scope}
        try:
            raw = paid(name, params, 'Commercial screening')
            if not isinstance(raw, dict): raise ValueError('Unrecognised commercial response')
            evidence['raw'][name] = raw
            data = raw.get('result', raw.get('data', {}))
            if not isinstance(data, dict): raise ValueError('Unrecognised commercial result')
            if name == 'rents-commercial':
                if not numeric(data.get('avg_quoting_rent_per_sqft')):
                    raise ValueError('No commercial quoting-rent sample returned')
            elif name.startswith('valuation-commercial-'):
                key = 'estimate_annual' if name.endswith('-rent') else 'estimate'
                value = numeric(data.get(key))
                if value is None or value <= 0: raise ValueError('No usable commercial valuation returned')
            evidence['market'][name] = data
        except Exception as exc:
            source.update(status='error', detail=scrub(str(exc)) if isinstance(exc, ValueError) else 'Commercial evidence unavailable')
            evidence['errors'].append({'source': name, 'message': source['detail']})
        evidence['sources'].append(source)
        progress('Researching: ' + source['title'])
    return evidence
