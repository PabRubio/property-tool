import copy
import json
import os
import subprocess
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from app import create_app, provenance
from test_intake import brief
from test_report_evidence import record, inputs, comp
from screening.assumptions import letting_strategy
from screening.comparisons import comparison_summary, exact_address
from screening.evidence import enriched_inputs
from screening.finance import analyse
from screening.internal_report import generate_internal
from screening.narrative import deterministic, validate_client_prose, plan_revision
from screening.reports import generate_report
from screening.research import research, web_search, apply_findings
from screening.schema import validate_submission
from screening.tax_summary import tax_summary


class BudgetPolicyTests(unittest.TestCase):
    def test_strategy_defaults_and_explicit_rate(self):
        i=provenance(validate_submission(brief()),supplied=brief())
        self.assertEqual(analyse(i,{},'manual')['effective_assumptions']['management_pct'],14.4)
        i['analyst_notes']='This is an HMO let to students.'
        self.assertEqual(analyse(i,{},'manual')['effective_assumptions']['management_pct'],18)
        i['analyst_notes']='It could be an HMO, but not currently.'
        self.assertEqual(letting_strategy(i),'whole_house')
        i['assumptions']['management_pct']=12
        i['input_provenance']['assumptions.management_pct']={'basis':'User / analyst input'}
        i['analyst_notes']='This is an HMO.'
        self.assertEqual(analyse(i,{},'manual')['effective_assumptions']['management_pct'],12)

    def test_legacy_default_upgrades_and_scoped_quote_can_replace_it(self):
        i=inputs();i['assumptions']['management_pct']=12
        i['input_provenance']['assumptions.management_pct']={'basis':'Illustrative default (unverified)'}
        self.assertEqual(analyse(i,{},'manual')['effective_assumptions']['management_pct'],14.4)
        quote={'management_pct':15,'vat_included':True,'applicable_strategy':'whole_house',
               'local_provider':'Example local agent','service_scope':'full_management'}
        e={'researched_facts':{'costs':{'value':quote,'source_ids':['research-fee'],'evidence_date':date.today().isoformat()}}}
        self.assertEqual(analyse(i,e,'manual')['effective_assumptions']['management_pct'],15)
        quote['vat_included']=False
        self.assertEqual(analyse(i,e,'manual')['effective_assumptions']['management_pct'],14.4)

    def test_fire_costs_count_once_and_funding_is_not_a_return_test(self):
        i=inputs();base=analyse(i,{},'manual')
        i['assumptions'].update(fire_safety_upfront=2000,fire_safety_annual=120,licensing_annual=240)
        i['investor']['cash_budget']=1
        m=analyse(i,{},'manual')
        self.assertEqual(m['metrics']['cash_required']-base['metrics']['cash_required'],2000)
        self.assertAlmostEqual(base['metrics']['monthly_cashflow_before_tax']-m['metrics']['monthly_cashflow_before_tax'],30)
        self.assertEqual(len(m['tests']),2)
        self.assertGreater(m['funding']['extra_cash_needed'],0)
        self.assertEqual(m['monthly'][0]['maintenance'],base['monthly'][0]['maintenance'])

    def test_uplift_is_once_after_works_with_no_uplift_sensitivity(self):
        i=inputs();i['assumptions'].update(refurbishment_planned=True,refurb_level='refurb_light',refurbishment=20000,
                                         price_growth_pct=0,rent_growth_pct=0,initial_void_months=18)
        m=analyse(i,{},'manual')
        self.assertEqual(m['refurbishment_uplift']['amount'],10000)
        self.assertEqual(m['annual'][0]['property_value'],250000)
        self.assertEqual(m['annual'][1]['property_value'],260000)
        self.assertEqual(m['annual'][-1]['property_value'],260000)
        self.assertEqual(m['refurbishment_uplift']['no_uplift_sale_price'],250000)
        self.assertAlmostEqual(m['exit']['total_profit']-m['refurbishment_uplift']['no_uplift_total_profit'],9850)
        self.assertEqual(m['metrics']['monthly_rent'],1520)
        i['assumptions']['refurb_value_uplift']=35000
        self.assertEqual(analyse(i,{},'manual')['exit']['sale_price'],285000)
        i['assumptions'].update(refurbishment_planned=False,refurb_level='none',refurbishment=0)
        self.assertEqual(analyse(i,{},'manual')['refurbishment_uplift']['amount'],0)

    def test_tax_is_ownership_specific_and_never_infers_a_bill(self):
        i=inputs();m=analyse(i,{},'manual')
        self.assertIn('basic-rate tax reduction',tax_summary(m))
        i['assumptions']['buyer_type']='company';m=analyse(i,{},'manual')
        self.assertIn('Corporation Tax',tax_summary(m))
        self.assertNotIn('basic-rate tax reduction',tax_summary(m))
        self.assertIn('Annual income tax is excluded',tax_summary(m))

    def test_supported_lower_after_works_value_is_not_replaced_by_optimism(self):
        i=inputs();i['assumptions'].update(refurbishment_planned=True,refurb_level='refurb_light',refurbishment=20000,price_growth_pct=0)
        rows=[dict(comp(j),source_id='research-'+str(j)) for j in range(3)]
        refs=[r['source_id'] for r in rows]
        e={'comparables':rows,'researched_facts':{'refurbishment.uplift':{'value':{'after_works_value':240000,'comparable_source_ids':refs,'basis':'Renovated comparison evidence'},'source_ids':refs}}}
        m=analyse(i,e,'manual')
        self.assertEqual(m['refurbishment_uplift']['amount'],-10000)
        self.assertEqual(m['exit']['sale_price'],240000)
        self.assertLess(m['exit']['total_profit'],m['refurbishment_uplift']['no_uplift_total_profit'])

    def test_cost_evidence_preserves_client_and_requires_scope(self):
        r=record();r['inputs']['assumptions']['fire_safety_annual']=None
        result={'sources':[{'id':'w','url':'https://example.com/quote','title':'Quote','support':['Annual servicing for this property']}], 'queries':['quote'], 'errors':[]}
        gap=[{'id':'assumptions.fire_safety_annual','provider_result':'Unpriced'}]
        value={'amount':120,'unit':'GBP_per_year','vat_included':True,'frequency_confirmed':True,
               'landlord_responsibility_confirmed':True,'excludes_existing_budgets':True,'basis':'Quoted annual cost'}
        f={'gap_id':gap[0]['id'],'status':'supported','value_json':json.dumps(value),'source_ids':['w'],
           'matched_address':'12 Example Road','matched_postcode':'M1 1AA','scope':'cost','text':'Annual quote','limitations':''}
        self.assertEqual(apply_findings(r,gap,result,{'findings':[f]},1)[0]['status'],'supported')
        self.assertEqual(enriched_inputs(r['inputs'],r['evidence'])['assumptions']['fire_safety_annual'],120)
        r['inputs']['assumptions']['fire_safety_annual']=80
        self.assertEqual(enriched_inputs(r['inputs'],r['evidence'])['assumptions']['fire_safety_annual'],80)
        f['matched_address']='99 Other Road'
        self.assertEqual(apply_findings(r,gap,result,{'findings':[f]},1)[0]['status'],'inconclusive')


class IterationTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'ANTHROPIC_API_KEY':'test','RESEARCH_MAX_ROUNDS':'3','RESEARCH_MAX_SECONDS':'60'})
        self.env.start();self.addCleanup(self.env.stop)
        self.gap={'id':'property.bathrooms','label':'Bathrooms','group':'property','provider_result':'Missing'}
        self.result={'sources':[{'id':'w','url':'https://example.com/house','title':'Listing','support':['Two bathrooms']}],
                     'text':'Listing','queries':[{'query':'12 Example Road bathrooms'}],'errors':[]}
        self.finding={'gap_id':'property.bathrooms','status':'supported','text':'Two bathrooms','value_json':'2','source_ids':['w'],
                      'matched_address':'12 Example Road','matched_postcode':'M1 1AA','scope':'subject','limitations':'','unresolved_reason':'','next_search':''}

    def run_research(self,r,findings,**kwargs):
        with patch('screening.narrative.choose_model',return_value='test'),patch('screening.research.gaps',return_value=[self.gap]),\
             patch('screening.research.web_search',return_value=copy.deepcopy(self.result)) as search,\
             patch('screening.research.extract',side_effect=findings),patch('screening.research.review_gaps',return_value=[]):
            research(r,'anthropic',**kwargs)
        return search

    def test_second_round_resolves_gap_with_prior_findings_and_checkpoint(self):
        r=record();first=dict(self.finding,status='inconclusive',value_json='null',unresolved_reason='not_found',next_search='Read agent floor plan')
        saved=[]
        search=self.run_research(r,[{'findings':[first]},{'findings':[self.finding]}],checkpoint=lambda:saved.append(copy.deepcopy(r['evidence'])))
        self.assertEqual(search.call_count,2)
        self.assertEqual(search.call_args.args[3]['previous_findings'][0]['next_search'],'Read agent floor plan')
        self.assertEqual(r['evidence']['research']['status'],'completed')
        self.assertEqual(r['evidence']['researched_facts']['property.bathrooms']['value'],2)
        self.assertGreaterEqual(len(saved),2)

    def test_limits_are_incomplete_and_retry_does_not_cache_failure(self):
        r=record();f=dict(self.finding,status='inconclusive',value_json='null',unresolved_reason='not_found')
        self.run_research(r,[{'findings':[f]}]*3)
        self.assertEqual(r['evidence']['research']['status'],'incomplete')
        self.assertEqual(r['evidence']['research']['stop_reason'],'round_limit')
        self.assertEqual(self.run_research(r,[{'findings':[self.finding]}]).call_count,1)

    def test_completed_cache_invalidates_for_notes(self):
        r=record();self.run_research(r,[{'findings':[self.finding]}])
        self.assertEqual(self.run_research(r,[]).call_count,0)
        r['inputs']['analyst_notes']='An extension changed the bathroom layout.'
        self.assertEqual(self.run_research(r,[{'findings':[self.finding]}]).call_count,1)

    def test_failed_review_is_retried_even_when_facts_are_supported(self):
        r=record()
        with patch('screening.narrative.choose_model',return_value='test'),patch('screening.research.gaps',return_value=[self.gap]),\
             patch('screening.research.web_search',return_value=copy.deepcopy(self.result)),\
             patch('screening.research.extract',return_value={'findings':[self.finding]}),\
             patch('screening.research.review_gaps',side_effect=ValueError('Review failed')):
            research(r,'anthropic')
        self.assertEqual(r['evidence']['research']['status'],'partial_failure')
        with patch('screening.narrative.choose_model',return_value='test'),patch('screening.research.gaps',return_value=[self.gap]),\
             patch('screening.research.web_search') as search,patch('screening.research.review_gaps',return_value=[]) as review:
            research(r,'anthropic')
        self.assertEqual(search.call_count,0)
        self.assertEqual(review.call_count,1)
        self.assertEqual(r['evidence']['research']['status'],'completed')

    def test_public_gap_cannot_be_dismissed_as_private(self):
        r=record();f=dict(self.finding,status='inconclusive',value_json='null',unresolved_reason='private_document')
        result=apply_findings(r,[self.gap],self.result,{'findings':[f]},1)
        self.assertEqual(result[0]['unresolved_reason'],'not_found')

    def test_failed_retry_preserves_collected_sources_and_comparisons(self):
        r=record();r['evidence']['comparables']=[comp(0)]
        r['evidence']['sources']=[{'id':'research-existing','url':'https://example.com/existing'}]
        with patch('screening.narrative.choose_model',return_value='test'),patch('screening.research.gaps',return_value=[self.gap]),\
             patch('screening.research.web_search',side_effect=ValueError('Connection failed')):
            research(r,'anthropic')
        self.assertEqual(len(r['evidence']['comparables']),1)
        self.assertEqual(r['evidence']['sources'][0]['id'],'research-existing')
        self.assertEqual(r['evidence']['research']['status'],'partial_failure')

    def test_fetch_citations_and_pause_continuation(self):
        first={'stop_reason':'pause_turn','content':[{'type':'server_tool_use','name':'web_fetch','input':{'url':'https://example.com/plan.pdf'}},
                {'type':'web_fetch_tool_result','content':{'type':'web_fetch_result','url':'https://example.com/plan.pdf','content':{'type':'document','title':'Floor plan'}}}]}
        second={'stop_reason':'end_turn','content':[{'type':'text','text':'Two bathrooms','citations':[{'type':'page_location','document_index':0,'cited_text':'Bathroom / shower room'}]}]}
        with patch('screening.research.request_json',side_effect=[first,second]) as request:
            result=web_search('anthropic','test','test',{})
        self.assertEqual(result['sources'][0]['url'],'https://example.com/plan.pdf')
        self.assertEqual(result['sources'][0]['support'],['Bathroom / shower room'])
        self.assertEqual(request.call_count,2)
        self.assertTrue(any(t['name']=='web_fetch' for t in request.call_args.kwargs['body']['tools']))


class DeliveryTests(unittest.TestCase):
    def test_manual_edits_fill_missing_inputs_without_another_research_run(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'ANTHROPIC_API_KEY':'test'}):
            app=create_app(folder);i=inputs();i['property'].update(asking_price=None,price_status='unknown')
            i['investor']['cash_budget']=50000
            i['assumptions'].update(purchase_price=None,monthly_rent=None)
            r=app.store.create(i,mode='live');r['analysis']=analyse(i,{},'manual')
            r['artifacts']=generate_report(r,app.store.folder(r['id']));r['status']='ready_for_review';app.store.save(r)
            self.assertEqual(r['artifacts']['page_count'],10)
            self.assertIsNone(r['analysis']['metrics']['monthly_cashflow_before_tax'])
            def plan(original,provider,instruction):
                updated=copy.deepcopy(original['inputs'])
                field,value=('monthly_rent',1800) if instruction=='Set rent' else ('purchase_price',180000)
                updated['assumptions'][field]=value
                return updated,'Supplied input applied',[{'section':'assumptions','key':field,'value':value}],{},True,{'requested':False,'questions':[]}
            with patch('app.plan_revision',side_effect=plan),patch('app.generate',side_effect=lambda rec,*args,**kwargs:deterministic(rec)),\
                 patch('screening.research.research') as research_call,patch('app.gather') as gather_call:
                for instruction,complete in [('Set rent',False),('Set price',True)]:
                    response=app.test_client().post('/api/records/'+r['id']+'/revise',json={'revision':r['revision'],'instruction':instruction},headers={'X-Local-Token':app.csrf_token})
                    self.assertEqual(response.status_code,202,response.get_json())
                    for _ in range(400):
                        r=app.store.load(r['id'])
                        if r.get('job',{}).get('state') in ('done','failed'):break
                        time.sleep(.02)
                    self.assertEqual(r['job']['state'],'done',r['job'])
                    self.assertEqual(r['analysis']['available'],complete)
                    self.assertEqual(r['artifacts']['page_count'],10)
                    self.assertGreater(r['analysis']['monthly'][0]['collected_rent'],0)
                    self.assertIsNotNone(r['analysis']['purchase_guidance']['funding_price_ceiling'])
                    if not complete:
                        operating_income=r['analysis']['metrics']['stabilised_noi']
                        self.assertIsNone(r['analysis']['metrics']['monthly_cashflow_before_tax'])
                    for key in ('cashflow_csv','cashflow_png','calculations_png','sources_pdf','internal_pdf'):
                        self.assertTrue((app.store.folder(r['id'])/r['artifacts'][key]).is_file())
                research_call.assert_not_called();gather_call.assert_not_called()
                self.assertIsNotNone(r['analysis']['metrics']['monthly_cashflow_before_tax'])
                self.assertEqual(r['analysis']['metrics']['stabilised_noi'],operating_income)
                self.assertNotIn('usage',r)
                time.sleep(.03)

    def test_close_bedroom_comparisons_are_used_and_differences_disclosed(self):
        from screening.report_layout import client_comparisons
        i=inputs();rows=[dict(comp(j),bedrooms=5) for j in range(3)]
        rows.append(dict(comp(5),bedrooms=3,distance=.01))
        summary=comparison_summary(i,{'comparables':rows},'sold')
        self.assertEqual(summary['count'],3)
        self.assertIsNotNone(summary['median'])
        self.assertEqual(summary['candidates'][0]['bedrooms'],5)
        self.assertTrue(any('5 vs 6' in x for x in summary['matched'][0]['limitations']))
        self.assertEqual(client_comparisons(summary['candidates'],i['property'])[0]['bedrooms'],5)
        duplicate=dict(rows[0],address='20, Example Road, M1 1AA',postcode=None)
        rows[0]['address']='20 Example Road, Manchester M1 1AA'
        self.assertEqual(comparison_summary(i,{'comparables':rows+[duplicate]},'sold')['count'],3)

    def test_comparison_identity_and_bedroom_priority(self):
        i=inputs();near=comp(1,'asking');near.update(bedrooms=3,distance=.01)
        correct=comp(2,'asking');correct.update(distance=2,tenure=None)
        rows=comparison_summary(i,{'comparables':[near,correct]},'asking')['candidates']
        self.assertEqual(rows[0]['bedrooms'],6)
        self.assertFalse(exact_address({'address':'Example Road M1 1AA'}))
        street=[dict(comp(j,'asking'),address='Example Road') for j in range(2)]
        self.assertEqual(len(comparison_summary(i,{'comparables':street},'asking')['candidates']),2)
        self.assertEqual(comparison_summary(i,{'comparables':street},'asking')['count'],0)

    def test_pdf_separates_internal_actions_and_retains_photo_placeholder(self):
        r=record();r['evidence']['comparables']=[comp(j,'asking') for j in range(5)]
        r['analysis']=analyse(r['inputs'],r['evidence'],'manual');r['narrative']=deterministic(r)
        with tempfile.TemporaryDirectory() as folder:
            art=generate_report(r,folder)
            text=subprocess.check_output(['pdftotext',str(Path(folder)/art['pdf']),'-'],text=True)
            internal=subprocess.check_output(['pdftotext',str(Path(folder)/art['internal_pdf']),'-'],text=True)
            self.assertIn('Property photograph not supplied',text)
            self.assertNotIn('Add a subject-property photograph before delivery',text)
            self.assertIn('Subject photograph',internal)
            self.assertNotIn('Verify conflicting records',text)
            self.assertNotIn('Cash needed within investor budget',text)
            self.assertNotIn('[model',text)
            self.assertIn('Tax review',text)
            self.assertEqual(art['page_count'],10)
            self.assertEqual(art['internal_page_count'],1)
            self.assertIn(b'google.com/maps/search', (Path(folder)/art['pdf']).read_bytes())

    def test_client_instruction_validator_keeps_limitation(self):
        with self.assertRaises(ValueError):validate_client_prose({'summary':{'text':'Verify the bedroom count before delivery.'}})
        validate_client_prose({'summary':{'text':'The rent is a supplied assumption; achievable rent remains uncertain.'},
                               'due_diligence':[{'text':'Verify bedroom count.'}]})

    def test_risk_paragraphs_go_to_the_requested_pdf(self):
        r=record();r['analysis']=analyse(r['inputs'],r['evidence'],'manual');r['narrative']=deterministic(r)
        private=[
            'The 6-bedroom basis is unverified. The EPC record shows 7 habitable rooms and an estimated 3 bedrooms. Sale and rent valuation requests were skipped.',
            'Price support is weak. The proposed £300,000 compares with a £125,000 sale in 2022.',
            'Costs are incomplete. Regular and changeover cleaning are excluded, not assumed free.']
        public=[
            'If let as a multi-occupancy house, licensing may apply. Licensing status for this address is not established. These costs are not in the model.',
            'Financing is unverified. Interest-only means £270,000 remains to repay at exit. Income tax and disposal tax are excluded.',
            'Surface-water flood risk and listed status are unresolved. River/sea risk does not establish surface-water risk.',
            'The purchase price exceeds the return-based ceiling. The monthly cash-flow target is not met.']
        r['narrative']['content']['risks']=[{'text':s,'source_ids':['model']} for s in private+public]
        r['narrative']['content']['due_diligence']=[]
        r['analysis']['flags']=[]
        with tempfile.TemporaryDirectory() as folder:
            art=generate_report(r,folder)
            client=' '.join(subprocess.check_output(['pdftotext',str(Path(folder)/art['pdf']),'-'],text=True).split())
            staff=' '.join(subprocess.check_output(['pdftotext',str(Path(folder)/art['internal_pdf']),'-'],text=True).split())
            for text in private:
                self.assertNotIn(text,client)
                self.assertIn(text,staff)
            for text in public:
                self.assertIn(text,client)
            self.assertEqual(art['page_count'],10)
            self.assertEqual(art['internal_page_count'],1)

    def test_large_internal_handoff_stays_one_page_with_full_record(self):
        r=record();r['evidence']['research']={'status':'incomplete','findings':[
            {'gap_id':'review.task_'+str(i),'status':'inconclusive','text':'Research details '*100,'unresolved_reason':'not_found'} for i in range(80)]}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'internal.pdf';generate_internal(r,path)
            info=subprocess.check_output(['pdfinfo',str(path)],text=True)
            self.assertRegex(info,r'Pages:\s+1\b')
            self.assertEqual(len(r['internal_review']['items']),81)

    def test_editor_can_request_research_without_inventing_input_changes(self):
        r=record();r['analysis']=analyse(r['inputs'],r['evidence'],'manual')
        plan={'can_apply':True,'message':'Research matching six-bedroom listings.','changes':[],
              'text_edits':[],'style_changes':[],'page_order':None,'rewrite_commentary':True,
              'research_requested':True,'research_questions':['Find full addresses for the best six-bedroom comparisons.']}
        with patch.dict(os.environ,{'ANTHROPIC_API_KEY':'test'}),patch('screening.narrative.choose_model',return_value='test'),patch('screening.narrative.call_model',return_value=plan):
            result=plan_revision(r,'anthropic','Find better comparisons and their exact addresses.')
        self.assertTrue(result[5]['requested'])
        self.assertEqual(result[2],[])

    def test_revision_route_runs_research_and_preserves_old_report_on_failure(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'ANTHROPIC_API_KEY':'test'}):
            app=create_app(folder);r=app.store.create(inputs(),mode='live')
            r['analysis']=analyse(r['inputs'],{},'manual');r['narrative']=deterministic(r)
            r['artifacts']={'pdf':'original.pdf'};r['report_document']={'saved':{'original':'Title','text':'Title','kind':'heading'}}
            app.store.save(r)
            plan=(copy.deepcopy(r['inputs']),'Research requested',[],{},True,{'requested':True,'questions':['Resolve full comparison addresses']})
            with patch('app.plan_revision',return_value=plan),patch('screening.research.research') as research_call,\
                 patch('app.generate',side_effect=ValueError('Writer unavailable')):
                response=app.test_client().post('/api/records/'+r['id']+'/revise',json={'revision':1,'instruction':'Find addresses'},headers={'X-Local-Token':app.csrf_token})
                self.assertEqual(response.status_code,202)
                for _ in range(100):
                    saved=app.store.load(r['id'])
                    if saved.get('job',{}).get('state')=='failed':break
                    time.sleep(.02)
                self.assertEqual(research_call.call_count,1)
                self.assertTrue(research_call.call_args.kwargs['draft_report'])
                self.assertEqual(saved['artifacts']['pdf'],'original.pdf')
                self.assertEqual(saved['revision'],1)


if __name__=='__main__':unittest.main()
