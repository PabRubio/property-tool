"""Commercial screening must not inherit residential facts or tax assumptions."""
import copy
import json
from datetime import date
import unittest
from unittest.mock import patch

from screening.schema import validate, validate_submission
from screening.providers import gather
from screening.evidence import valuation
from screening.finance import analyse, project, stamp_duty


def commercial_brief(kind='retail'):
    return {
        'enquiry': {'terms_accepted': True},
        'investor': {'name': 'Test investor', 'email': 'test@example.com'},
        'property': {'address': '10 Example Street', 'postcode': 'M1 1AA',
                     'asset_class': 'commercial', 'property_type': kind,
                     'floor_area_sqm': 100, 'floor_area_basis': 'nia' if kind == 'offices' else 'gia',
                     'tenure': 'freehold', 'occupancy': 'let', 'asking_price': 275000,
                     'price_status': 'listed', 'rent_vat_status': 'exempt'},
        'assumptions': {'financing': 'cash', 'buyer_type': 'individual',
                        'annual_rent': 24000, 'lease_remaining_months': 60,
                        'purchase_vat_pct': 0, 'refurb_level': 'none',
                        'management_pct': 5, 'maintenance_pct': 2, 'insurance': 500,
                        'compliance': 300, 'letting_fees': 0, 'safety_upfront': 0,
                        'void_cost_monthly': 100, 'business_rates_annual': 6000,
                        'regular_cleaning': 0, 'turnover_cleaning': 0,
                        'service_charge': 0, 'ground_rent': 0},
    }


class CommercialSchemaTests(unittest.TestCase):
    def test_residential_remains_default(self):
        out = validate({'property': {'address': '1 Test Road', 'postcode': 'M1 1AA'}})
        self.assertEqual(out['property']['asset_class'], 'residential')
        self.assertEqual(out['property']['bedrooms'], 2)

    def test_three_commercial_types_need_no_bedrooms_or_residential_buyer_questions(self):
        for kind in ('retail', 'offices', 'industrial'):
            out = validate_submission(commercial_brief(kind))
            self.assertEqual(out['property']['property_type'], kind)
            self.assertIsNone(out['property']['bedrooms'])
            self.assertEqual(out['assumptions']['monthly_rent'], 2000)
            self.assertEqual(out['assumptions']['annual_rent'], 24000)

    def test_unsupported_scope_is_rejected(self):
        for changes in ({'unit_count': 2}, {'mixed_use': True}, {'property_type': 'pubs'},
                        {'country': 'Wales'}, {'asset_class': 'other'}):
            data = commercial_brief()
            data['property'].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_submission(data)

    def test_annual_and_monthly_rents_must_agree(self):
        data = commercial_brief()
        data['assumptions']['monthly_rent'] = 24000
        with self.assertRaisesRegex(ValueError, 'annual.*monthly|Annual.*monthly'):
            validate(data)

    def test_commercial_months_and_vat_are_validated(self):
        for values in ({'lease_remaining_months': 1.5}, {'break_month': -1},
                       {'purchase_vat_pct': 5}, {'purchase_vat_recoverable_pct': 101},
                       {'purchase_vat_pct': 20, 'purchase_vat_recoverable_pct': 100}):
            data = commercial_brief()
            data['assumptions'].update(values)
            with self.subTest(values=values), self.assertRaises(ValueError):
                validate(data)

    def test_unknown_commercial_fields_are_preserved_for_incomplete_reports(self):
        data = commercial_brief()
        del data['assumptions']['purchase_vat_pct']
        del data['assumptions']['lease_remaining_months']
        out = validate_submission(data)
        self.assertIsNone(out['assumptions']['purchase_vat_pct'])
        self.assertIsNone(out['assumptions']['lease_remaining_months'])

    def test_wrong_or_unknown_measurement_does_not_change_supplied_area(self):
        data = commercial_brief('offices')
        data['property']['floor_area_basis'] = 'gia'
        out = validate(data)
        self.assertEqual(out['property']['floor_area_basis'], 'gia')
        self.assertEqual(out['property']['floor_area_sqm'], 100)


class CommercialProviderTests(unittest.TestCase):
    def gather(self, data, replies=None):
        replies = replies or {
            'rents-commercial': {'data': {'points_analysed': 42, 'unit_type': 'NIA', 'avg_quoting_rent_per_sqft': 45, 'avg_quoting_rent': 96750}},
            'valuation-commercial-rent': {'result': {'estimate_annual': 23000, 'estimate_monthly': 1917, 'margin_annual': 2500}},
            'valuation-commercial-sale': {'result': {'estimate': 375000, 'margin': 55000}},
        }
        with patch.dict('os.environ', {'PROPERTYDATA_API_KEY': 'test'}), \
             patch('screening.providers.request_json', return_value={'result': {'country': 'England'}}), \
             patch('screening.providers.pd_call', side_effect=lambda name, params: replies[name]) as calls:
            result = gather(validate(data))
        return result, calls

    def test_commercial_requests_and_annual_units(self):
        evidence, calls = self.gather(commercial_brief('offices'))
        self.assertEqual({c.args[0] for c in calls.call_args_list},
                         {'rents-commercial', 'valuation-commercial-rent', 'valuation-commercial-sale'})
        self.assertEqual(calls.call_args_list[1].args[1]['area_unit'], 'sqm')
        self.assertEqual(valuation(evidence, 'rent'), round(23000 / 12, 2))
        self.assertEqual(valuation(evidence, 'sale'), 375000)
        self.assertNotIn('monthly_rent', evidence['market'])
        self.assertEqual(evidence['asset_class'], 'commercial')

    def test_wrong_area_basis_skips_valuations_without_changing_facts(self):
        data = commercial_brief('offices')
        data['property']['floor_area_basis'] = 'gia'
        evidence, calls = self.gather(data)
        self.assertEqual([c.args[0] for c in calls.call_args_list], ['rents-commercial'])
        self.assertIsNone(valuation(evidence, 'rent'))
        self.assertTrue(evidence['errors'])

    def test_provider_failure_is_not_a_residential_fallback(self):
        evidence, calls = self.gather(commercial_brief(), {'rents-commercial': {}})
        self.assertEqual(len(calls.call_args_list), 3)
        self.assertIsNone(valuation(evidence, 'rent'))
        self.assertTrue(evidence['errors'])

    def test_commercial_evidence_never_uses_legacy_residential_valuation(self):
        evidence = {'asset_class': 'commercial', 'market': {'valuation-rent': {'estimate': 1000, 'unit': 'gbp_per_month'}}}
        self.assertIsNone(valuation(evidence, 'rent'))


class CommercialFinanceTests(unittest.TestCase):
    def model(self, changes=None, property_changes=None, evidence=None):
        data = commercial_brief()
        data['assumptions'].update(changes or {})
        data['property'].update(property_changes or {})
        return analyse(validate(data), evidence or {}, 'manual')

    def test_nonresidential_sdlt_ignores_residential_surcharges(self):
        for price, expected in ((150000, 0), (150001, .02), (250000, 2000), (275000, 3250), (600000, 19500)):
            a = dict(validate(commercial_brief())['assumptions'], _asset_class='commercial',
                     buyer_type='company', nonresident=True, additional_property=True)
            self.assertEqual(stamp_duty(price, a)['total'], expected)

    def test_vat_increases_taxable_consideration_and_upfront_cash(self):
        plain = self.model()
        taxed = self.model({'purchase_vat_pct': 20, 'purchase_vat_recoverable_pct': 100, 'vat_recovery_month': 3})
        self.assertEqual(taxed['sdlt']['total'], 6000)
        self.assertEqual(taxed['metrics']['cash_required'] - plain['metrics']['cash_required'], 57750)
        self.assertEqual(taxed['monthly'][2]['vat_recovery'], 55000)
        self.assertEqual(sum(r['vat_recovery'] for r in taxed['monthly']), 55000)
        self.assertEqual(taxed['monthly'][2]['net_operating_income'], plain['monthly'][2]['net_operating_income'])

    def test_income_stops_at_earliest_break_and_review_is_not_applied_afterwards(self):
        m = self.model({'break_month': 6, 'rent_review_month': 12, 'rent_review_annual_rent': 36000,
                        'void_pct': 0, 'holding_years': 3})
        self.assertEqual(m['monthly'][5]['collected_rent'], 2000)
        self.assertEqual(m['monthly'][6]['collected_rent'], 0)
        self.assertEqual(m['monthly'][12]['collected_rent'], 0)
        self.assertEqual(m['monthly'][6]['business_rates'], 500)

    def test_rent_review_free_period_and_explicit_reletting(self):
        m = self.model({'lease_remaining_months': 12, 'rent_free_months': 2, 'rent_review_month': 6,
                        'rent_review_annual_rent': 30000, 'reletting_void_months': 3,
                        'reletting_annual_rent': 36000, 'void_pct': 0, 'cost_growth_pct': 0})
        self.assertEqual([r['collected_rent'] for r in m['monthly'][:3]], [0, 0, 2000])
        self.assertEqual(m['monthly'][6]['collected_rent'], 2500)
        self.assertEqual([r['collected_rent'] for r in m['monthly'][12:16]], [0, 0, 0, 3000])
        self.assertEqual(m['monthly'][0]['business_rates'], 0)  # Rent-free occupation is not vacant.

    def test_missing_commercial_terms_withhold_returns(self):
        for values in ({'purchase_vat_pct': None}, {'lease_remaining_months': None}):
            model = self.model(values)
            self.assertFalse(model['available'])
            self.assertIsNone(model['metrics']['net_yield_on_cost_pct'])
            self.assertFalse(model['monthly'])

    def test_residential_growth_and_valuations_do_not_leak(self):
        stale = {'market': {'valuation-sale': {'estimate': 900000}, 'monthly_rent': 5000,
                            'growth': {'data': [['2023-01', 100], ['2025-01', 200]]}}}
        m = self.model(evidence=stale)
        self.assertEqual(m['starting_value'], 275000)
        self.assertEqual(m['effective_assumptions']['price_growth_pct'], 0)
        self.assertEqual(m['effective_assumptions']['rent_growth_pct'], 0)
        self.assertEqual(m['metrics']['monthly_rent'], 2000)

    def test_unknown_commercial_costs_do_not_use_residential_defaults(self):
        data = commercial_brief()
        for key in ('management_pct', 'maintenance_pct', 'insurance', 'compliance', 'letting_fees', 'safety_upfront'):
            del data['assumptions'][key]
        m = analyse(validate(data), {}, 'manual')
        self.assertEqual(m['effective_assumptions']['management_pct'], 0)
        self.assertTrue(any('unpriced' in f['detail'].lower() for f in m['flags']))

    def test_selected_residential_or_unknown_unit_rents_cannot_supply_commercial_rent(self):
        for kind, basis in [('flat', 'whole_property_monthly'), ('retail', 'unknown'), ('retail', 'commercial_unit_annual')]:
            data = commercial_brief()
            data['assumptions'].pop('annual_rent')
            data['comparables'] = [{'kind': 'rent', 'address': '12 Example Street', 'amount': 900,
                'date': date.today().isoformat(), 'source_url': 'https://example.com/rent',
                'property_type': kind, 'rental_basis': basis, 'floor_area_basis': 'gia', 'selected': True}]
            m = analyse(validate(data), {}, 'manual', include_horizons=False)
            self.assertFalse(m['available'])
            self.assertIsNone(m['metrics']['monthly_rent'])

    def test_cost_table_reconciles_to_lease_aware_headline_schedule(self):
        m = self.model({'lease_remaining_months': 6, 'void_pct': 0, 'cost_growth_pct': 0,
                        'management_pct': 5, 'rent_review_month': 3, 'rent_review_annual_rent': 30000})
        costs = {r['key']: r['annual'] for r in m['operating_costs']}
        rows = m['monthly'][:12]
        self.assertEqual(costs['management_pct'], sum(r['management'] for r in rows))
        self.assertEqual(costs['void_cost_monthly'], sum(r['void_costs'] for r in rows))
        self.assertEqual(costs['maintenance_pct'], sum(r['maintenance'] for r in rows))
        self.assertEqual(sum(r['annual'] or 0 for r in m['operating_costs']), m['annual'][0]['operating_costs'])

    def test_no_break_even_when_initial_rent_cannot_cover_costs(self):
        m = self.model({'break_month': 0, 'void_pct': 0})
        self.assertIsNone(m['metrics']['break_even_rent'])

    def test_break_even_rent_solves_first_year_lease_cashflow(self):
        m = self.model({'lease_remaining_months': 6, 'void_pct': 0, 'cost_growth_pct': 0})
        rent = m['metrics']['break_even_rent']
        self.assertIsNotNone(rent)
        rows, _, _ = project(dict(m['effective_assumptions'], holding_years=1, initial_void_months=0), 275000, rent)
        self.assertAlmostEqual(sum(r['cashflow_before_tax'] for r in rows), 0, delta=.12)


class CommercialQuoteTests(unittest.TestCase):
    def grounded_rows(self, quote, amount):
        from screening.codex_research import grounded
        url = 'https://example.com/commercial'
        row = {'address': '12 High Street', 'postcode': 'M1 1AA', 'kind': 'rent', 'amount': amount,
               'rental_basis': 'commercial_unit_monthly', 'source_ids': [url], 'source_url': url, 'evidence_quote': quote}
        finding = {'gap_id': 'comparisons.rent', 'status': 'supported', 'scope': 'comparison',
                   'source_ids': [url], 'evidence_quote': quote, 'value_json': json.dumps([row])}
        result = grounded({'findings': [finding]}, [{'id': url, 'url': url, 'support': [quote]}])
        return json.loads(result['findings'][0]['value_json'])

    def test_per_area_annual_prices_are_not_unit_rents(self):
        for unit in ('per square foot', 'per sq ft', 'per sq. ft', 'psf', 'per square metre', '/m²'):
            quote = '12 High Street M1 1AA Rent £24 per annum ' + unit + ' exclusive of VAT.'
            self.assertEqual(self.grounded_rows(quote, 2), [], unit)

    def test_explicit_annual_total_converts_to_monthly(self):
        quote = '12 High Street M1 1AA Total rent £24,000 per annum exclusive of VAT.'
        self.assertEqual(len(self.grounded_rows(quote, 2000)), 1)


if __name__ == '__main__':
    unittest.main()
