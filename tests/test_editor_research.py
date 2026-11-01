"""Offline tests of the web-enabled editor and its staged evidence updates."""
import copy
import importlib
import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from screening.finance import analyse
from screening.narrative import plan_revision
from test_report_evidence import record, comp
from test_codex_research import bathroom, scrape, URL
from test_cost_estimates import proposal, QUOTE
from test_lacewing_updates import build, pages, pdf_text
from screening.narrative import deterministic
from screening.reports import generate_report
from app import create_app


def findings_result(findings=None, calls=None, costs=None):
    return {'output':{'findings':findings or [],'estimates':[],'cost_estimates':costs or []},
            'tool_calls':calls or [],'model':'test'}


def planned(research=None, **changes):
    output=dict(can_apply=True,message='Requested edit prepared.',changes=[],text_edits=[],
                style_changes=[],page_order=None,rewrite_commentary=True,
                research=(research or findings_result())['output'])
    output.update(changes)
    return dict(research or findings_result(),output=output)


def locality(r):
    text='Example Park and local bus services serve the M1 1AA area.'
    item=dict(bathroom(r),gap_id='property.nearby_places',scope='area',text=text,
              value_json=json.dumps(text),evidence_quote=text)
    return item,scrape(text)


class EditorPlanning(unittest.TestCase):
    def test_editor_enables_firecrawl_and_passes_evidence_without_contact_details(self):
        r=record();r['analysis']=analyse(r['inputs'],r['evidence'],'live');before=copy.deepcopy(r)
        r['inputs']['investor'].update(name='Private Investor',email='private@example.test')
        with patch('screening.codex.run',return_value=planned()) as run:
            result=plan_revision(r,'codex','Research nearby transport and update the report')
        self.assertTrue(run.call_args.kwargs.get('research'))
        packet=run.call_args.args[1]
        self.assertIn('research_context',packet)
        self.assertNotIn('private@example.test',json.dumps(packet))
        self.assertNotIn('Private Investor',json.dumps(packet))
        self.assertEqual(len(result),6)
        self.assertEqual(r['evidence'],before['evidence'])

    def test_web_planner_cannot_disguise_an_unrequested_fee_as_supplied_input(self):
        r=record();change={'section':'assumptions','key':'legal_fees','value':1234}
        reply=planned(findings_result([bathroom(r)],[scrape()]),changes=[change])
        with patch('screening.codex.run',side_effect=[reply,{'output':{'changes':[]}}]),self.assertRaisesRegex(ValueError,'explicit|supplied'):
            plan_revision(r,'codex','Research the number of bathrooms and legal fees')

    def test_mixed_explicit_correction_and_research_keeps_extraction_separate(self):
        r=record();change={'section':'assumptions','key':'legal_fees','value':1234}
        reply=planned(findings_result([bathroom(r)],[scrape()]),changes=[change])
        with patch('screening.codex.run',side_effect=[reply,{'output':{'changes':[change]}}]) as run:
            result=plan_revision(r,'codex','Set legal fees to £1,234 and research the number of bathrooms')
        self.assertEqual(result[0]['assumptions']['legal_fees'],1234)
        self.assertEqual(run.call_count,2)
        args=run.call_args_list[-1]
        self.assertFalse(args.kwargs.get('research',False))
        self.assertNotIn('research_context',args.args[1])
        self.assertNotIn('The property has two bathrooms.',json.dumps(args.args[1]))
        self.assertNotIn('changes',args.args[1])


class EditorEvidence(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('screening.edit_research'),'Editor evidence integration is missing')
        self.editor=importlib.import_module('screening.edit_research')

    def test_cited_amenities_reach_analysis_without_erasing_other_findings(self):
        r=record();r['evidence']['raw']={'property':{'bedrooms_estimate':5}}
        r['evidence']['research']={'findings':[{'gap_id':'costs','status':'supported','text':'Existing cost scope','source_ids':['inputs']}]}
        before=copy.deepcopy(r['inputs']);finding,call=locality(r)
        audit=self.editor.apply(r,findings_result([finding],[call]))
        self.assertTrue(audit['changed'])
        self.assertEqual(r['inputs'],before)
        self.assertEqual(r['evidence']['raw'],{'property':{'bedrooms_estimate':5}})
        self.assertEqual({f['gap_id'] for f in r['evidence']['research']['findings']},{'costs','property.nearby_places'})
        model=analyse(r['inputs'],r['evidence'],'live')
        self.assertIn('Example Park',r['evidence']['researched_facts']['property.nearby_places']['value'])
        self.assertTrue(model['available'])
        self.assertTrue(r['evidence']['researched_facts']['property.nearby_places']['source_ids'][0].startswith('research-'))

    def test_invented_citations_and_search_snippets_cannot_support_edits(self):
        for calls,url in [([scrape()],'https://invented.example/house'),([dict(scrape(),tool='firecrawl_search')],URL)]:
            r=record()
            with self.subTest(url=url),self.assertRaisesRegex(ValueError,'evidence|supported'):
                self.editor.apply(r,findings_result([bathroom(r,url)],calls))

    def test_cost_research_updates_calculations_but_preserves_supplied_costs(self):
        r=record();original=copy.deepcopy(r['inputs'])
        self.editor.apply(r,findings_result(calls=[scrape(QUOTE)],costs=[dict(proposal(),source_ids=[URL])]))
        self.assertEqual(analyse(r['inputs'],r['evidence'],'live')['effective_assumptions']['legal_fees'],1800)
        self.assertEqual(r['inputs'],original)
        r['inputs']['assumptions']['legal_fees']=2500
        r['inputs']['input_provenance']['assumptions.legal_fees']={'basis':'User / analyst input'}
        self.assertEqual(analyse(r['inputs'],r['evidence'],'live')['effective_assumptions']['legal_fees'],2500)

    def test_plain_edit_preserves_all_evidence(self):
        r=record();before=copy.deepcopy(r)
        self.assertFalse(self.editor.apply(r,findings_result())['changed'])
        self.assertEqual(r,before)

    def test_missing_rent_can_be_estimated_from_existing_comparisons_without_changing_input(self):
        from screening import estimates
        r=record();r['inputs']['assumptions']['monthly_rent']=None
        r['evidence'].update(sources=[{'id':'example','status':'ok','url':'https://example.com'}],
            comparables=[dict(comp(i,'rent'),rental_basis='whole_property_monthly') for i in range(2)])
        value={'kind':'rent','estimate':1600,'low':1500,'high':1700,
               'basis':'Nearby comparable houses adjusted for the subject layout.',
               'limitations':'Advertised rents; actual condition and achieved rents unverified.',
               'comparable_ids':[c['id'] for c in estimates.candidates(r)]}
        reply=findings_result();reply['output']['estimates']=[value]
        self.editor.apply(r,reply)
        self.assertIsNone(r['inputs']['assumptions']['monthly_rent'])
        model=analyse(r['inputs'],r['evidence'],'live')
        self.assertEqual(model['metrics']['monthly_rent'],1600)
        self.assertIn('Analyst estimate',model['rent_basis'])

    def test_failed_validation_is_atomic_even_with_another_valid_finding(self):
        r=record();before=copy.deepcopy(r);finding,call=locality(r)
        bad=bathroom(r,'https://invented.example/house')
        with self.assertRaises(ValueError):self.editor.apply(r,findings_result([finding,bad],[call]))
        self.assertEqual(r,before)

    def test_quota_or_no_supported_results_cannot_claim_a_research_edit(self):
        r=record();call=dict(scrape(),status='failed',error={'message':'Daily limit reached'})
        with self.assertRaisesRegex(ValueError,'Firecrawl|limit'):
            self.editor.apply(r,findings_result(calls=[call]))

    def test_researched_area_invalidates_dependent_outputs_but_preserves_provider_facts(self):
        r=record();r['inputs']['property']['floor_area_sqm']=None
        r['evidence'].update(market={'valuation-sale':{'estimate':250000},'build-cost':{'cost':50000},'asking_price_per_sqft':200},
            raw={'valuation-sale':{'status':'success'},'build-cost':{'status':'success'},'prices-per-sqf':{'status':'success'},'property':{'unchanged':True}},
            sources=[{'id':sid,'status':'ok'} for sid in ('valuation-sale','build-cost','prices-per-sqf')],
            comparables=[dict(comp(0),source_id='prices-per-sqf')])
        text='12 Example Road, M1 1AA. The floor area is 100 square metres.'
        finding=dict(bathroom(r),gap_id='property.floor_area_sqm',value_json='100',text=text,evidence_quote=text)
        self.editor.apply(r,findings_result([finding],[scrape(text)]))
        self.assertEqual(r['evidence']['researched_facts']['property.floor_area_sqm']['value'],100)
        self.assertEqual(r['evidence']['raw'],{'property':{'unchanged':True}})
        self.assertEqual(r['evidence']['market'],{})
        self.assertEqual(r['evidence']['comparables'],[])
        self.assertTrue(r['evidence']['sources'][0]['id'].startswith('research-'))


class EditorRoute(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.app=create_app(self.folder.name);self.client=self.app.test_client()
        self.headers={'X-Local-Token':self.app.csrf_token}
        self.r=self.app.store.create(build()['inputs'],'demo')
        self.r['analysis']=analyse(self.r['inputs'],self.r['evidence'],'demo')
        self.r['narrative']=deterministic(self.r)
        self.r['presentation']={'text':{},'style':{'accent_color':'#19766e'}}
        self.r['artifacts']=generate_report(self.r,self.app.store.folder(self.r['id']))
        self.r['status']='ready_for_review';self.app.store.save(self.r)

    def edit(self,reply,writer=None):
        with patch('screening.codex.run',return_value=reply),patch('app.generate',side_effect=writer or (lambda r,p,**kw:deterministic(r))):
            response=self.client.post('/api/records/'+self.r['id']+'/revise',
                json={'revision':self.r['revision'],'provider':'codex','instruction':'Research nearby amenities and legal fees; update the report.'},headers=self.headers)
            self.assertEqual(response.status_code,202)
            for _ in range(500):
                saved=self.app.store.load(self.r['id'])
                if saved.get('job',{}).get('state') in ('done','failed'):return saved
                time.sleep(.01)
            self.fail('Edit job did not finish')

    def test_researched_edit_rebuilds_ten_pages_and_sources_with_recalculated_fees(self):
        finding,call=locality(self.r)
        research=findings_result([finding],[call,scrape(QUOTE+' '+finding['text'])],[dict(proposal(),source_ids=[URL])])
        saved=self.edit(planned(research))
        self.assertEqual(saved['job']['state'],'done',saved['job'])
        self.assertEqual(saved['analysis']['effective_assumptions']['legal_fees'],1800)
        self.assertEqual(saved['inputs']['assumptions']['legal_fees'],self.r['inputs']['assumptions']['legal_fees'])
        self.assertEqual(saved['presentation'],self.r.get('presentation',{}))
        self.assertEqual(saved['photos'],self.r['photos'])
        self.assertTrue(saved['edit_history'][-1]['research']['changed'])
        folder=self.app.store.folder(saved['id'])
        self.assertEqual(pages(folder/saved['artifacts']['pdf']),10)
        self.assertIn('Example Park',pdf_text(folder/saved['artifacts']['pdf']))
        self.assertIn('agent.example',pdf_text(folder/saved['artifacts']['sources_pdf']))

    def test_writer_failure_after_research_preserves_existing_report_and_evidence(self):
        finding,call=locality(self.r)
        path=self.app.store.folder(self.r['id'])/self.r['artifacts']['pdf'];before=path.read_bytes()
        saved=self.edit(planned(findings_result([finding],[call])),writer=ValueError('Writer failed'))
        self.assertEqual(saved['job']['state'],'failed')
        for key in ('inputs','evidence','analysis','artifacts','revision'):
            self.assertEqual(saved[key],self.r[key])
        self.assertEqual(path.read_bytes(),before)

    def test_style_only_edit_keeps_evidence_and_commentary_without_research(self):
        reply=planned(rewrite_commentary=False,style_changes=[{'key':'accent_color','value':'#112233'}])
        saved=self.edit(reply,writer=AssertionError('Style edit must not rewrite commentary'))
        self.assertEqual(saved['job']['state'],'done',saved['job'])
        self.assertEqual(saved['presentation']['style']['accent_color'],'#112233')
        self.assertEqual(saved['evidence'],self.r['evidence'])
        self.assertEqual(saved['narrative'],self.r['narrative'])

    def test_failed_research_records_diagnostics_without_replacing_report(self):
        finding,call=locality(self.r)
        finding['evidence_quote']='Invented wording that was never on the page.'
        saved=self.edit(planned(findings_result([finding],[call])))
        self.assertEqual(saved['job']['state'],'failed')
        self.assertTrue('last_failed_edit' in saved,'Failed edit diagnostics were discarded')
        self.assertIn('Research nearby',saved['last_failed_edit']['request'])
        self.assertTrue(saved['last_failed_edit']['research']['tool_calls'])
        for key in ('inputs','evidence','analysis','artifacts','revision'):
            self.assertEqual(saved[key],self.r[key])

    def test_planner_refusal_retains_the_observed_pages_and_original_response(self):
        finding,call=locality(self.r)
        reply=planned(findings_result([finding],[call]),can_apply=False,message='More local evidence is needed.')
        saved=self.edit(reply)
        self.assertEqual(saved['job']['state'],'failed')
        research=saved['last_failed_edit']['research']
        self.assertIsNotNone(research,'Planner refusal discarded the response and page results')
        self.assertEqual(research['tool_calls'],[call])
        self.assertFalse(research['planner_output']['can_apply'])


if __name__=='__main__':unittest.main()
