"""Disclosed modelling choices; supplied values always take precedence."""
import re
from .schema import defaults


def effective_defaults(inputs):
    a = dict(defaults()['assumptions'], **inputs['assumptions'])
    provenance = inputs.get('input_provenance', {})
    basis = {key: provenance.get('assumptions.'+key, {}).get('basis', 'Supplied / saved input; unverified') for key in a}
    notes = ' '.join([inputs['investor'].get('notes', ''), inputs['property'].get('listing_notes', ''),
                      inputs.get('analyst_notes', ''), a.get('rent_source', '')]).lower()
    # Bedroom count alone says nothing about the tenancy arrangement. Questions,
    # negations and possible future conversions do not establish a shared let.
    shared = False
    for sentence in re.split(r'[.!?;\n]', notes):
        if re.search(r'\b(no|not|non|possible|potential|consider|considering|convert|conversion|if|might|could|whether)\b', sentence): continue
        if re.search(r'\b(hmo|shared (?:house|letting|tenancy)|student(?:-style)? (?:let|letting|house|rental|accommodation)|let (?:by the room|to students))\b', sentence): shared = True
    strategy = 'Established shared / HMO / student letting stated in notes' if shared else 'Ordinary whole-house letting; no established shared arrangement stated'
    def defaulted(key):
        return key not in inputs['assumptions'] or basis[key].startswith('Illustrative default') or a[key] is None
    if defaulted('management_pct'):
        a['management_pct'] = 18 if shared else 14.4
        basis['management_pct'] = 'Modelling default incl. VAT: '+strategy.lower()
    if defaulted('compliance'):
        a['compliance'] = 500 if shared else 250
        basis['compliance'] = ('Illustrative annual safety allowance: gas checks where applicable, electrical inspection provision, '
                               'alarm testing/replacement'+('; shared-system servicing provision' if shared else '')+'. No separate recurring fire charge.')
    included = a.get('safety_included_in', 'none')
    # Existing cost notes may explicitly place the safety work in another budget.
    if included == 'none':
        match = re.search(r'(?:fire|safety|alarms?).{0,35}(?:included|covered).{0,20}(refurbishment|works budget|other purchase)', a.get('cost_source', ''), re.I)
        if match: included = 'other_purchase_costs' if match[1].lower()=='other purchase' else 'refurbishment'
    if included != 'none':
        a['safety_upfront'] = 0
        basis['safety_upfront'] = 'Included in '+included.replace('_',' ')+'; no duplicate allowance added'
    elif defaulted('safety_upfront'):
        a['safety_upfront'] = 600 if shared else 150
        basis['safety_upfront'] = ('Illustrative upfront '+('shared fire-safety assessment / alarm provision' if shared else 'smoke / CO alarm provision')+
                                  '; not a quote or a full remedial-works budget. Major fire works and licence fees remain unpriced.')
    a['safety_included_in'] = included
    return a, basis, strategy


def works_value(a, current_value, evidence):
    if a['refurb_level'] == 'none':
        return {'uplift':0, 'after_works_value':current_value, 'basis':'No refurbishment has been selected for this property', 'source_ids':['assumptions']}
    supported = evidence.get('researched_facts', {}).get('assumptions.after_works_value', {})
    value = a.get('after_works_value')
    refs = ['assumptions']
    basis = 'Supplied after-works value: '+(a.get('after_works_source') or 'unverified investor / analyst scenario')
    if value is None and isinstance(supported.get('value'), (int,float)) and supported['value'] > 0:
        value = supported['value']; refs = supported.get('source_ids') or ['assumptions']
        basis = 'Supported after-works value: '+supported.get('text', 'saved research')
    if value is None:
        uplift = a.get('refurbishment')
        if uplift is not None: uplift *= a['refurbishment_value_recovery_pct']/100
        value = current_value+uplift if current_value is not None and uplift is not None else None
        basis = ('Illustrative partial cost-recovery scenario: '+str(a['refurbishment_value_recovery_pct'])+
                 '% of works budget, excluding contingency. Allows for costs that do not add resale value; '
                 'not a valuation or evidence of market recovery. Assumes works completed before exit; no separate rent uplift.')
    return {'uplift':round(value-current_value,2) if value is not None and current_value is not None else None,
            'after_works_value':value, 'basis':basis, 'source_ids':refs}
