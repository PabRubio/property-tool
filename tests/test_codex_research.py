"""Research boundaries and estimate consumption; no paid/network services."""
import copy
import importlib
import json
import unittest
from unittest.mock import patch

from test_report_evidence import record as base_record, comp
from screening.finance import analyse


URL = 'https://agent.example/house'


def record():
    # These tests isolate evidence validation; locality scheduling is exercised
    # separately in test_research_followups with a genuinely missing locality.
    r=base_record()
    r['evidence']['researched_facts']={'property.nearby_places':{
        'value':'Previously established locality context.', 'source_ids':['inputs']}}
    return r


def scrape(text='12 Example Road, M1 1AA. The property has two bathrooms.'):
    return {'type': 'mcpToolCall', 'server': 'firecrawl', 'tool': 'firecrawl_scrape',
            'status': 'completed', 'arguments': {'url': URL},
            'result': {'content': [{'type': 'text', 'text': json.dumps({
                'success': True, 'markdown': text, 'metadata': {'sourceURL': URL}})}]}}


def answer(findings=None, done=False, calls=None):
    return {'output': {'findings': findings or [], 'estimates': [], 'done': done,
                       'next_searches': [], 'summary': 'Checked evidence.'},
            'tool_calls': calls or [], 'model': 'test'}


def bathroom(r, url=URL):
    return {'gap_id': 'property.bathrooms', 'status': 'supported', 'text': 'Two bathrooms.',
            'value_json': '2', 'source_ids': [url], 'matched_address': r['inputs']['property']['address'],
            'matched_postcode': r['inputs']['property']['postcode'], 'evidence_date': '',
            'scope': 'subject', 'limitations': '', 'evidence_quote': 'The property has two bathrooms.'}


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('screening.codex_research'), 'Research adapter missing')
        self.research = importlib.import_module('screening.codex_research')

    def test_follows_up_and_retains_findings_without_changing_provider_data(self):
        r = record(); original = copy.deepcopy(r['inputs'])
        r['evidence']['raw'] = {'property': {'bedrooms_estimate': 5}}
        replies = [answer([bathroom(r)], calls=[scrape()]), answer(done=True)]
        with patch('screening.codex_research.run', side_effect=replies) as run:
            self.research.research(r)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(r['inputs'], original)
        self.assertEqual(r['evidence']['raw'], {'property': {'bedrooms_estimate': 5}})
        self.assertEqual(r['evidence']['researched_facts']['property.bathrooms']['value'], 2)
        self.assertIn('unresolved', r['evidence']['research'])

    def test_invented_citation_and_search_snippets_cannot_fill_facts(self):
        for calls, url in [([scrape()], 'https://invented.example/house'),
                           ([dict(scrape(), tool='firecrawl_search')], URL)]:
            r = record()
            with patch('screening.codex_research.run', return_value=answer([bathroom(r, url)], done=True, calls=calls)):
                self.research.research(r)
            self.assertNotIn('property.bathrooms', r['evidence'].get('researched_facts', {}))

    def test_two_dead_ends_stop_without_exhausting_time_budget(self):
        r = record()
        with patch('screening.codex_research.run', return_value=answer()) as run:
            self.research.research(r)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(r['evidence']['research']['stop_reason'], 'No useful progress in two rounds')

    def test_unrelated_page_cannot_be_assigned_the_subject_address(self):
        for address in ('99 Other Road, M2 2BB', '112 Example Road, M1 1AA'):
            r = record()
            with patch('screening.codex_research.run', return_value=answer([bathroom(r)], done=True,
                       calls=[scrape(address + '. The property has two bathrooms.')])):
                self.research.research(r)
            self.assertNotIn('property.bathrooms', r['evidence'].get('researched_facts', {}))

    def test_room_or_weekly_quote_cannot_be_relabelled_monthly_whole_house(self):
        for description in ('room to let for £350 per week', 'house to let for £350 per week',
                            'room to let for £350 per month'):
            r = record(); quote = '20 Example Road, M1 1AA: ' + description
            row = dict(comp(0, 'rent'), amount=350, rental_basis='whole_property_monthly',
                       source_url=URL, source_ids=[URL], evidence_quote=quote, notes='')
            finding = dict(bathroom(r), gap_id='comparisons.rent', scope='comparison',
                           value_json=json.dumps([row]), evidence_quote=quote)
            with patch('screening.codex_research.run', return_value=answer([finding], done=True, calls=[scrape(quote)])):
                self.research.research(r)
            self.assertFalse(r['evidence']['comparables'])

    def test_explicit_monthly_house_quote_is_accepted(self):
        r = record(); quote = '20 Example Road, M1 1AA: whole house to let for £1,500 pcm'
        row = dict(comp(0, 'rent'), amount=1500, rental_basis='whole_property_monthly',
                   source_url=URL, source_ids=[URL], evidence_quote=quote, notes='')
        finding = dict(bathroom(r), gap_id='comparisons.rent', scope='comparison',
                       value_json=json.dumps([row]), evidence_quote=quote)
        with patch('screening.codex_research.run', return_value=answer([finding], done=True, calls=[scrape(quote)])):
            self.research.research(r)
        self.assertEqual(r['evidence']['comparables'][0]['amount'], 1500)

    def test_timeout_keeps_previous_checkpoint_and_actual_sources(self):
        from screening.codex import CodexTimeout
        r = record()
        with patch('screening.codex_research.run', side_effect=[answer([bathroom(r)], calls=[scrape()]), CodexTimeout([scrape()])]):
            self.research.research(r)
        self.assertEqual(r['evidence']['researched_facts']['property.bathrooms']['value'], 2)
        self.assertEqual(r['evidence']['research']['status'], 'partial_failure')
        self.assertEqual(len(r['evidence']['research']['batches']), 2)

    def test_real_page_formatting_and_unknown_postcode_keep_useful_comparison(self):
        r = record()
        passage = '## 28, Long Acres, Durham DH1 1JF\\n\\n| 14 Nov 2025 | £175,000 |'
        row = {'address': '28 Long Acres, Durham', 'postcode': None, 'kind': 'sold', 'amount': 175000,
               'source_url': URL, 'source_ids': [URL],
               'evidence_quote': '28, Long Acres, Durham DH1 1JF … 14 Nov 2025 | £175,000'}
        finding = dict(bathroom(r), gap_id='comparisons.sold', scope='comparison',
                       value_json=json.dumps([row]), evidence_quote='14 Nov 2025 | £175,000')
        with patch('screening.codex_research.run', return_value=answer([finding], done=True, calls=[scrape(passage)])):
            self.research.research(r)
        self.assertEqual(r['evidence']['comparables'][0]['address'], '28 Long Acres, Durham')
        self.assertIsNone(r['evidence']['comparables'][0]['postcode'])

    def test_later_round_does_not_erase_specific_unresolved_reason(self):
        r = record()
        finding = dict(bathroom(r), status='inconclusive', value_json='null', text='Exact subject listing was blocked.')
        with patch('screening.codex_research.run', side_effect=[answer([finding]), answer(done=True)]):
            self.research.research(r)
        result = next(f for f in r['evidence']['research']['findings'] if f['gap_id'] == 'property.bathrooms')
        self.assertEqual(result['text'], 'Exact subject listing was blocked.')


class EstimateTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('screening.estimates'), 'Evidence-backed estimates missing')
        self.estimates = importlib.import_module('screening.estimates')
        self.r = record()
        self.r['inputs']['property']['asking_price'] = None
        self.r['inputs']['assumptions'].update(purchase_price=None, monthly_rent=None)
        rows = [dict(comp(i, kind), bedrooms=5, rental_basis='whole_property_monthly')
                for kind in ('rent', 'sold') for i in range(2)]
        self.r['evidence'].update(comparables=rows, sources=[{'id': 'example', 'status': 'ok', 'url': 'https://example.com'}])

    def proposed(self, kind):
        rows = self.estimates.candidates(self.r)
        ids = [c['id'] for c in rows if c['kind'] == ('sold' if kind == 'sale' else kind)]
        value = 260000 if kind == 'sale' else 1600
        return {'kind': kind, 'estimate': value, 'low': value * .9, 'high': value * 1.1,
                'basis': 'Nearby five-bedroom houses adjusted for the supplied six-bedroom layout.',
                'limitations': 'Extra bedroom and condition need review; asking rent is not achieved rent.',
                'comparable_ids': ids}

    def test_near_matches_support_labelled_estimates_only_for_blanks(self):
        r = self.r; original = copy.deepcopy(r['inputs'])
        self.estimates.apply(r, [self.proposed('rent'), self.proposed('sale')])
        model = analyse(r['inputs'], r['evidence'], 'live')
        self.assertTrue(model['available'])
        self.assertEqual(model['metrics']['purchase_price'], 260000)
        self.assertEqual(model['effective_assumptions']['monthly_rent'], 1600)
        self.assertIn('Analyst estimate', model['rent_basis'])
        self.assertIn('Analyst estimate', model['price_basis'])
        self.assertEqual(r['inputs'], original)
        r['inputs']['property']['asking_price'] = 280000
        r['inputs']['assumptions']['monthly_rent'] = 1900
        model = analyse(r['inputs'], r['evidence'], 'live')
        self.assertEqual(model['metrics']['purchase_price'], 280000)
        self.assertEqual(model['effective_assumptions']['monthly_rent'], 1900)

    def test_invented_or_duplicate_comparables_do_not_support_estimate(self):
        for ids in [['invented', 'also-invented'], ['duplicate', 'duplicate']]:
            estimate = dict(self.proposed('rent'), comparable_ids=ids)
            self.estimates.apply(self.r, [estimate])
            self.assertFalse(self.r['evidence'].get('estimates', {}).get('rent'))

    def test_per_room_rent_and_changed_property_invalidate_estimates(self):
        proposed = self.proposed('rent')
        for row in self.r['evidence']['comparables']:
            if row['kind'] == 'rent': row['rental_basis'] = 'per_room'
        self.estimates.apply(self.r, [proposed])
        self.assertFalse(self.r['evidence'].get('estimates', {}).get('rent'))
        self.estimates.apply(self.r, [self.proposed('sale')])
        self.r['inputs']['property']['bedrooms'] = 9
        self.assertIsNone(self.estimates.get(self.r['inputs'], self.r['evidence'], 'sale'))

    def test_changed_supporting_facts_invalidate_estimate(self):
        self.estimates.apply(self.r, [self.proposed('sale')])
        for row in self.r['evidence']['comparables']:
            row.update(bedrooms=1, floor_area_sqm=15, property_type='flat', tenure='leasehold')
        self.assertIsNone(self.estimates.get(self.r['inputs'], self.r['evidence'], 'sale'))

    def test_writer_never_receives_invalid_estimates_or_their_findings(self):
        from screening.narrative import generate
        self.estimates.apply(self.r, [self.proposed('sale')])
        self.r['evidence']['research'] = {'findings': [{'gap_id': 'estimate.sale', 'text': 'Codex estimate £260,000'}]}
        self.r['inputs']['property'].update(bathrooms=3, asking_price=280000)
        self.r['inputs']['assumptions']['monthly_rent'] = 1900
        self.r['analysis'] = analyse(self.r['inputs'], self.r['evidence'], 'live')
        with patch('screening.narrative.call_model', side_effect=ValueError('Stop after capturing packet')) as model:
            generate(self.r, 'codex')
        packet = model.call_args.args[3]
        self.assertEqual(packet['evidence_backed_estimates'], {})
        self.assertFalse(any(f.get('gap_id') == 'estimate.sale' for f in packet['research']))


if __name__ == '__main__':
    unittest.main()
