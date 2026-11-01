"""Cost evidence, calculation dependencies and client report wording."""
import copy
import importlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_lacewing_updates import build, pdf_text, pages
from screening.finance import analyse, project
from screening.narrative import deterministic
from screening.reports import generate_report

URL = 'https://local.example/fees'
QUOTE = 'Purchase legal services include VAT, searches and registration. Fees from £1,800.'


def proposal(kind='legal_fees', amount=1800, basis_type='fee'):
    return dict(kind=kind, estimate=amount, basis_type=basis_type,
                basis='Local published fees adjusted for the supplied freehold purchase.',
                limitations='Indicative budget; confirm the final scope and quote.',
                source_ids=[URL], evidence_quote=QUOTE, survey_level='not_applicable')


class CostEstimates(unittest.TestCase):
    def setUp(self):
        self.costs = importlib.import_module('screening.costs')
        self.r = build()
        self.source = dict(id=URL, url=URL, title='Local fee schedule', support=[QUOTE])

    def save(self, *items):
        return self.costs.apply(self.r, list(items), [self.source])

    def test_fees_require_real_quotes_and_preserve_supplied_inputs(self):
        original = copy.deepcopy(self.r['inputs'])
        self.assertFalse(self.save(dict(proposal(), evidence_quote='An invented quotation')))
        self.assertFalse(self.save(dict(proposal(), source_ids=['https://invented.example'])))
        self.assertTrue(self.save(proposal()))
        m = analyse(self.r['inputs'], self.r['evidence'], 'live')
        self.assertEqual(m['effective_assumptions']['legal_fees'], 1800)
        self.assertIn('Analyst estimate', m['modelling_basis']['legal_fees'])
        self.assertEqual(self.r['inputs'], original)

    def test_fallbacks_explicit_overrides_and_changed_property(self):
        m = analyse(self.r['inputs'], self.r['evidence'], 'live')
        self.assertEqual(m['effective_assumptions']['legal_fees'], 2000)
        self.assertEqual(m['effective_assumptions']['survey_fees'], 600)
        self.save(proposal(), dict(proposal('survey_fees', 800), survey_level='level_3'))
        self.r['inputs']['input_provenance']['assumptions.legal_fees'] = {'basis':'User / analyst input'}
        m = analyse(self.r['inputs'], self.r['evidence'], 'live')
        self.assertEqual(m['effective_assumptions']['legal_fees'], 2000)
        self.assertEqual(m['effective_assumptions']['survey_fees'], 800)
        self.r['inputs']['property']['tenure'] = 'leasehold'
        self.assertFalse(self.costs.current(self.r['inputs'], self.r['evidence']))

    def test_cost_scope_changes_and_expired_evidence_are_not_reused(self):
        self.save(proposal())
        self.r['inputs']['assumptions']['buyer_type']='company'
        self.assertFalse(self.costs.current(self.r['inputs'],self.r['evidence']))
        self.save(proposal())
        self.r['evidence']['cost_estimates']['legal_fees']['generated_at']='2020-01-01T00:00:00+00:00'
        self.assertFalse(self.costs.current(self.r['inputs'],self.r['evidence']))
        self.assertFalse(self.save(dict(proposal(), evidence_quote=None)))

    def test_saved_briefs_without_new_basis_field_consume_estimates(self):
        self.r['inputs']['assumptions'].pop('maintenance_basis')
        self.save(proposal())
        m=analyse(self.r['inputs'],self.r['evidence'],'live')
        self.assertEqual(m['effective_assumptions']['legal_fees'],1800)

    def test_letting_and_cost_scope_notes_invalidate_previous_estimates(self):
        self.save(proposal('management_pct',12,'collected_rent'))
        self.r['inputs']['assumptions']['rent_source']='Existing student letting arrangement'
        m=analyse(self.r['inputs'],self.r['evidence'],'live')
        self.assertIn('shared',m['letting_strategy'])
        self.assertEqual(m['effective_assumptions']['management_pct'],18)
        self.save(proposal())
        self.r['inputs']['assumptions']['cost_source']='Building repairs are included in the service charge'
        self.assertFalse(self.costs.current(self.r['inputs'],self.r['evidence']))

    def test_source_free_maintenance_cannot_claim_a_survey_quote(self):
        item=proposal('maintenance_pct',1,'property_value')
        item.update(source_ids=[],evidence_quote='The surveyor confirmed annual repair liability of exactly 1% of value.')
        self.assertFalse(self.save(item))
        item['evidence_quote']=''
        self.assertTrue(self.save(item))

    def test_research_cost_checkpoint_uses_scrapes_in_existing_round(self):
        self.r['evidence']['researched_facts']={'property.nearby_places':{'value':'Previously established locality context.'}}
        from screening.codex_research import research
        from test_codex_research import answer, scrape, URL as observed_url
        quote=QUOTE+' Full management is 10% plus VAT, excluding initial tenant-find fees.'
        fees=[proposal(),proposal('management_pct',12,'collected_rent')]
        for fee in fees:fee.update(source_ids=[observed_url],evidence_quote=quote)
        result=answer(done=True,calls=[scrape(quote)])
        result['output']['cost_estimates']=fees
        original=copy.deepcopy(self.r['inputs'])
        with patch('screening.codex_research.run',return_value=result) as run:
            research(self.r)
        self.assertEqual(run.call_count,1)
        self.assertEqual(self.r['inputs'],original)
        self.assertEqual(set(self.costs.current(self.r['inputs'],self.r['evidence'])),{'legal_fees','management_pct'})
        self.assertNotIn('cost.legal_fees',self.r['evidence']['research']['unresolved'])
        m=analyse(self.r['inputs'],self.r['evidence'],'live')
        self.assertEqual(m['effective_assumptions']['management_pct'],12)
        self.assertEqual(m['sdlt']['total'],self.r['analysis']['sdlt']['total'])
        self.assertEqual(m['metrics']['acquisition_costs'],self.r['analysis']['metrics']['acquisition_costs']-200)

    def test_unvalidated_cost_finding_does_not_close_the_cost_gap(self):
        self.r['evidence']['researched_facts']={'property.nearby_places':{'value':'Previously established locality context.'}}
        from screening.codex_research import research
        from test_codex_research import answer, scrape, bathroom
        finding=dict(bathroom(self.r),gap_id='cost.legal_fees',value_json='1800')
        with patch('screening.codex_research.run',return_value=answer([finding],done=True,calls=[scrape()])):
            research(self.r)
        self.assertIn('cost.legal_fees',self.r['evidence']['research']['unresolved'])
        self.assertFalse(self.r['evidence'].get('cost_estimates'))

    def test_management_is_local_inclusive_of_vat_and_not_a_setup_fee(self):
        self.assertFalse(self.save(proposal('management_pct', 12, 'fee')))
        self.save(proposal('management_pct', 12, 'collected_rent'))
        m = analyse(self.r['inputs'], self.r['evidence'], 'live')
        self.assertAlmostEqual(m['monthly'][0]['management'], 1520 * .95 * .12, places=2)
        row = next(c for c in m['operating_costs'] if c['key']=='management_pct')
        self.assertNotEqual(row['source_ids'], ['assumptions'])

    def test_value_maintenance_does_not_scale_with_rent_and_uses_cost_inflation(self):
        item = proposal('maintenance_pct', 1.2, 'property_value')
        item.update(source_ids=[], evidence_quote='', basis='Freehold house: allowance for fabric and fixtures; age not established.')
        self.save(item)
        m = analyse(self.r['inputs'], self.r['evidence'], 'live')
        a = m['effective_assumptions']
        self.assertEqual(a['maintenance_basis'], 'value')
        low = project(a, 250000, 1000)[0]
        high = project(a, 250000, 3000)[0]
        self.assertEqual(low[0]['maintenance'], 250)
        self.assertEqual(high[0]['maintenance'], 250)
        self.assertEqual(low[12]['maintenance'], 250 * (1+a['cost_growth_pct']/100))
        # A lower bid for this same property does not change its maintenance value basis.
        self.assertEqual(project(a, 180000, 1000)[0][0]['maintenance'], 250)
        be = project(dict(a, initial_void_months=0, holding_years=1), 250000, m['metrics']['break_even_rent'])[0]
        self.assertAlmostEqual(sum(x['cashflow_before_tax'] for x in be), 0, delta=.1)

    def test_rent_maintenance_and_independent_partial_value_cost(self):
        item = proposal('maintenance_pct', 4, 'scheduled_rent')
        item.update(source_ids=[], evidence_quote='', basis='Flat: internal repairs allowance; shared fabric excluded.')
        self.r['inputs']['property'].update(property_type='flat', tenure='leasehold')
        self.save(item)
        m = analyse(self.r['inputs'], self.r['evidence'], 'live')
        self.assertEqual(m['monthly'][0]['maintenance'], 60.8)
        self.r['inputs']['assumptions'].update(monthly_rent=None, maintenance_basis='value', maintenance_pct=1)
        self.r['inputs']['input_provenance']['assumptions.maintenance_pct']={'basis':'User / analyst input'}
        m = analyse(self.r['inputs'], self.r['evidence'], 'live')
        cost = next(c for c in m['operating_costs'] if c['key']=='maintenance_pct')
        self.assertEqual(cost['annual'], 2500)
        self.assertIsNone(next(c for c in m['operating_costs'] if c['key']=='management_pct')['annual'])

    def test_missing_value_does_not_zero_repairs_or_hide_independent_rent(self):
        self.r['inputs']['property']['asking_price']=None
        self.r['inputs']['assumptions']['maintenance_basis']='value'
        m=analyse(self.r['inputs'],self.r['evidence'],'live')
        self.assertIn('maintenance_value',m['missing'])
        self.assertIsNone(m['metrics']['stabilised_noi'])
        self.assertIsNone(next(c for c in m['operating_costs'] if c['key']=='maintenance_pct')['annual'])
        self.assertGreater(m['horizons'][0]['rental_income'],0)

    def test_pdfs_keep_pages_and_replace_codex_even_in_saved_commentary(self):
        self.save(proposal(), proposal('management_pct', 12, 'collected_rent'))
        self.r['analysis']=analyse(self.r['inputs'], self.r['evidence'], 'live')
        self.r['narrative']=deterministic(self.r)
        self.r['narrative']['content']['summary']['text']='Codex estimate retained as a scenario.'
        self.r['narrative']['content']['due_diligence']=[{'text':'Review the Codex estimate.', 'source_ids':['model']}]
        self.r['evidence']['sources'][0]['title']='Codex researched fee schedule'
        with tempfile.TemporaryDirectory() as folder:
            output=generate_report(self.r, folder)
            for key,count in [('pdf',10),('sources_pdf',1),('internal_review_pdf',1)]:
                p=Path(folder)/output[key]
                self.assertEqual(pages(p),count)
                self.assertNotIn('codex', pdf_text(p).lower())

    def test_writer_uses_five_ordered_risk_topics(self):
        from screening.narrative import generate
        self.r['analysis']=analyse(self.r['inputs'], self.r['evidence'], 'live')
        content=copy.deepcopy(deterministic(self.r)['content'])
        for key,value in content.items():
            if isinstance(value,dict):value['text']='Assessment remains conditional.'
            else:content[key]=[]
        topics=['financing','occupancy','cost_assumptions','exclusions','environment']
        content['risks']={topic:{'text':topic+' qualification.', 'source_ids':['model']} for topic in topics}
        with patch('screening.narrative.choose_model',return_value='test'), patch('screening.narrative.call_model',return_value=content) as model:
            result=generate(self.r,'codex',strict=True)
        self.assertEqual([x['text'] for x in result['content']['risks']],[t+' qualification.' for t in topics])
        schema=model.call_args.args[4]
        self.assertEqual(schema['properties']['risks']['required'],topics)


if __name__=='__main__':unittest.main()
