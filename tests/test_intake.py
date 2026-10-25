import copy
import os
import tempfile
import unittest
from unittest.mock import patch

from app import create_app
from screening.evidence import enriched_inputs
from screening.finance import analyse
from screening.narrative import generate
from screening.providers import gather
from screening.reports import generate_report
from screening.schema import validate_submission


def brief():
    return {
        'enquiry': {'terms_accepted': True},
        'investor': {'name': 'Example investor', 'email': 'investor@example.com'},
        'property': {'address': '12 Example Road', 'postcode': 'M1 1AA',
                     'property_type': 'semi-detached_house', 'bedrooms': 6,
                     'asking_price': 250000, 'price_status': 'listed'},
        'assumptions': {'financing': 'cash', 'buyer_type': 'individual',
                        'additional_property': False, 'nonresident': False,
                        'monthly_rent': 1520, 'refurb_level': 'none'},
    }


class IntakeTests(unittest.TestCase):
    def setUp(self):
        keys=patch.dict(os.environ,{'ANTHROPIC_API_KEY':'','OPENAI_API_KEY':'','GEMINI_API_KEY':''})
        keys.start();self.addCleanup(keys.stop)

    def test_recommended_details_can_be_omitted(self):
        result = validate_submission(brief())
        self.assertEqual(result['investor']['goal'], '')
        for key in ('floor_area_sqm', 'bathrooms', 'off_street_parking'):
            self.assertIsNone(result['property'][key])
        self.assertEqual(result['property']['bedrooms'], 6)
        self.assertEqual(result['assumptions']['refurbishment'], 0)

    def test_core_details_and_supplied_values_remain_validated(self):
        for section, field in [('investor', 'name'), ('investor', 'email'),
                               ('property', 'address'), ('property', 'postcode'),
                               ('property', 'property_type'), ('property', 'bedrooms'),
                               ('assumptions', 'financing'), ('assumptions', 'buyer_type')]:
            with self.subTest(field=field):
                payload = brief()
                del payload[section][field]
                with self.assertRaises(ValueError):
                    validate_submission(payload)
        for bedrooms in (-1, 5.5, 21):
            payload = brief()
            payload['property']['bedrooms'] = bedrooms
            with self.assertRaises(ValueError):
                validate_submission(payload)
        payload = brief()
        payload['property']['floor_area_sqm'] = 0
        with self.assertRaises(ValueError):
            validate_submission(payload)

    def test_area_enquiry_does_not_require_goal_or_property_details(self):
        payload = brief()
        payload['enquiry'].update(kind='area', area='Manchester', budget=250000)
        del payload['property']
        del payload['assumptions']
        result = validate_submission(payload)
        self.assertEqual(result['enquiry']['kind'], 'area')
        self.assertEqual(result['investor']['goal'], '')

    def test_mortgage_default_is_disclosed_and_explicit_terms_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            app = create_app(folder)
            client = app.test_client()
            for term in (None, 15, 25):
                with self.subTest(term=term):
                    payload = brief()
                    payload['assumptions'].update(financing='repayment', mortgage_amount=180000,
                                                  interest_rate_pct=5.5)
                    if term is not None:
                        payload['assumptions']['mortgage_term_years'] = term
                    response = client.post('/api/records', json={'inputs': payload},
                                           headers={'X-Local-Token': app.csrf_token})
                    self.assertEqual(response.status_code, 201, response.get_json())
                    record = response.get_json()
                    self.assertEqual(record['inputs']['assumptions']['mortgage_term_years'], term or 25)
                    model = analyse(record['inputs'], {}, 'manual')
                    self.assertTrue(model['available'])
                    assumed = [flag for flag in model['flags'] if flag['title'] == 'Full mortgage term assumed']
                    self.assertEqual(bool(assumed), term is None)
                    if assumed:
                        self.assertIn('25-year', assumed[0]['detail'])
                        record['analysis'] = model
                        record['narrative'] = generate(record, 'none')
                        artifacts = generate_report(record, app.store.folder(record['id']))
                        self.assertGreaterEqual(artifacts['page_count'], 10)
                        self.assertTrue(artifacts['sources_pdf'].endswith('-sources.pdf'))
                        rendered = '\n'.join(item['original'] for item in record['report_document'].values())
                        self.assertIn('25-year modelling assumption (full term not supplied)', rendered)
                        self.assertNotIn('Refurbishment reference:', rendered)
            for value in (0, 41, 5.5, '5-10'):
                payload['assumptions']['mortgage_term_years'] = value
                with self.assertRaises(ValueError):
                    validate_submission(payload)

    def test_no_refurbishment_rejects_conflicting_costs_and_ignores_old_estimates(self):
        payload = brief()
        payload['assumptions']['refurbishment'] = 20000
        with self.assertRaises(ValueError):
            validate_submission(payload)
        payload['assumptions']['refurbishment'] = 0
        payload['assumptions']['refurbishment_planned'] = True
        with self.assertRaises(ValueError):
            validate_submission(payload)
        model = analyse(validate_submission(brief()), {'market': {'build-cost': {'total_cost': 20000}}}, 'manual')
        self.assertEqual(model['metrics']['refurbishment_with_contingency'], 0)
        self.assertIsNone(model['refurbishment_reference']['estimate'])
        self.assertFalse(model['refurbishment_reference']['requested'])


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.patchers = [
            patch.dict(os.environ, {'PROPERTYDATA_API_KEY': 'offline-test'}),
            patch('screening.providers.request_json', return_value={'result': {'country': 'England'}}),
            patch('screening.providers.land_registry', return_value={'comparables': []}),
            patch('screening.providers.hpi', return_value={'series': []}),
            patch('screening.providers.pd_call', side_effect=self.provider),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def provider(self, endpoint, params):
        self.calls.append((endpoint, dict(params)))
        if endpoint == 'rents':
            return {'data': {'long_let': {'average': 350, 'unit': 'weekly', 'raw_data': []}}}
        if endpoint == 'property':
            return {'data': {'identity': {'data_status': 'found', 'address': '12 Example Road, M1 1AA'},
                             'building': {'data_status': 'found', 'internal_area_sqf': 646}}}
        if endpoint == 'build-cost':
            return {'data': {'total_cost': 10000}}
        return {'data': {}}

    def inputs(self, bedrooms=6, refurbishment='none', size=60):
        payload = brief()
        payload['property'].update(bedrooms=bedrooms, floor_area_sqm=size, bathrooms=2,
                                   construction_date='2000_onwards', finish_quality='average',
                                   outdoor_space='garden', off_street_parking=0)
        payload['assumptions'].update(refurb_level=refurbishment,
                                      refurbishment_planned=refurbishment != 'none')
        return validate_submission(payload)

    def test_six_bedrooms_use_broad_area_data_without_invalid_valuations(self):
        inputs = self.inputs()
        evidence = gather(inputs, include_profile=False)
        requests = dict(self.calls)
        for endpoint in ('rents', 'prices'):
            self.assertIn(endpoint, requests)
            self.assertNotIn('bedrooms', requests[endpoint])
            source = next(s for s in evidence['sources'] if s['id'] == endpoint)
            self.assertIn('all bedroom counts', source['scope'])
            self.assertEqual(source['status'], 'ok')
        for endpoint in ('valuation-sale', 'valuation-rent', 'build-cost', 'planning-applications'):
            self.assertNotIn(endpoint, requests)
            self.assertNotIn(endpoint, [r['endpoint'] for r in evidence['paid_requests']])
        self.assertFalse(any(e['source'] == 'build-cost' for e in evidence['errors']))
        self.assertTrue(evidence['market']['rent_bedroom_filter_omitted'])
        supplied = analyse(copy.deepcopy(inputs), copy.deepcopy(evidence), 'live')
        self.assertEqual(supplied['metrics']['monthly_rent'], 1520)
        inputs['assumptions']['monthly_rent'] = None
        fallback = analyse(inputs, evidence, 'live')
        self.assertTrue(fallback['available'])
        self.assertIn('all bedroom counts', fallback['rent_basis'])
        self.assertIn('6-bedroom', fallback['rent_basis'])

    def test_five_bedroom_filters_and_refurbishment_levels_still_work(self):
        for level in ('refurb_light', 'refurb_moderate', 'refurb_heavy'):
            with self.subTest(level=level):
                self.calls.clear()
                evidence = gather(self.inputs(5, level), include_profile=False)
                requests = dict(self.calls)
                for endpoint in ('rents', 'prices', 'valuation-sale', 'valuation-rent'):
                    self.assertEqual(requests[endpoint]['bedrooms'], 5)
                self.assertEqual(requests['build-cost']['project_type'], level)
                self.assertIn('planning-applications', requests)
                self.assertFalse(evidence['market']['rent_bedroom_filter_omitted'])

    def test_missing_floor_area_can_be_enriched_from_a_matched_profile(self):
        inputs = self.inputs(5, size=None)
        evidence = gather(inputs)
        self.assertIsNone(inputs['property']['floor_area_sqm'])
        found = enriched_inputs(inputs, evidence)
        self.assertAlmostEqual(found['property']['floor_area_sqm'], 60, delta=.1)
        self.assertEqual(dict(self.calls)['valuation-rent']['internal_area'], 646)


if __name__ == '__main__':
    unittest.main()
