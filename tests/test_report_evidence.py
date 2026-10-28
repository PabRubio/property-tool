import copy
import json
import subprocess
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from test_intake import brief
from screening.schema import validate_submission
from screening.finance import analyse, project, payment
from screening.comparisons import comparison_summary, months_ago, recent_sale
from screening.research import apply_findings, web_search, research
from screening.evidence import enriched_inputs
from screening.narrative import deterministic, generate, validate_figures
from screening.reports import generate_report


def inputs():
    b=brief();b['property'].update(floor_area_sqm=60,tenure='freehold')
    b['assumptions'].update(regular_cleaning=0,turnover_cleaning=0,service_charge=0,ground_rent=0)
    return validate_submission(b)


def record():
    i=inputs()
    return {'id':'test-report-evidence','revision':1,'mode':'live','inputs':i,
            'evidence':{'sources':[],'comparables':[]},'photos':[]}


def comp(index,kind='sold'):
    return {'address':str(index+20)+' Example Road','postcode':'M1 1AA','kind':kind,
            'amount':250000+index*1000 if kind=='sold' else 1500+index*20,
            'date':date.today().isoformat(),'observed_at':date.today().isoformat(),
            'bedrooms':6,'floor_area_sqm':60,'distance':.5,'tenure':'freehold',
            'property_type':'semi-detached_house','source_id':'example',
            'source_url':'https://example.com/property/'+str(index),'selected':False}


class FinanceEvidenceTests(unittest.TestCase):
    def test_deposits_and_optional_rate(self):
        b=brief();b['assumptions'].update(financing='interest_only',deposit_pct=25)
        i=validate_submission(b);m=analyse(i,{},'manual')
        self.assertEqual(m['metrics']['loan'],187500)
        self.assertEqual(m['effective_assumptions']['interest_rate_pct'],5.5)
        b['assumptions'].pop('deposit_pct');b['assumptions']['deposit_amount']=50000
        self.assertEqual(analyse(validate_submission(b),{},'manual')['metrics']['loan'],200000)
        b['assumptions']['deposit_pct']=20
        with self.assertRaises(ValueError):validate_submission(b)

    def test_repayment_and_interest_only_math_and_reset(self):
        a=inputs()['assumptions'];a.update(rent_growth_pct=0,financing='interest_only',mortgage_amount=500000,interest_rate_pct=5,mortgage_term_years=20,holding_years=3,fixed_rate_years=2,rate_after_fix_pct=7)
        rows,_,_=project(a,600000,4000)
        self.assertAlmostEqual(rows[0]['debt_payment'],500000*.05/12)
        self.assertAlmostEqual(rows[23]['debt_payment'],500000*.05/12)
        self.assertAlmostEqual(rows[24]['debt_payment'],500000*.07/12)
        a['mortgage_term_years']=35
        self.assertEqual(project(a,600000,4000)[0][0]['debt_payment'],rows[0]['debt_payment'])
        a.update(financing='repayment',mortgage_term_years=25)
        rows,_,_=project(a,600000,4000)
        self.assertAlmostEqual(rows[0]['debt_payment'],2922.9502,places=2)
        self.assertAlmostEqual(rows[24]['debt_payment'],payment(rows[23]['loan_balance'],7,23*12,'repayment'))
        self.assertLess(rows[24]['loan_balance'],rows[23]['loan_balance'])

    def test_cleaning_is_separate_and_counted_once(self):
        i=inputs();base=analyse(i,{},'manual');i['assumptions'].update(regular_cleaning=1200,turnover_cleaning=600)
        m=analyse(i,{},'manual')
        self.assertAlmostEqual(base['metrics']['monthly_cashflow_before_tax']-m['metrics']['monthly_cashflow_before_tax'],150)
        self.assertEqual(m['monthly'][0]['regular_cleaning'],100)
        self.assertEqual(m['monthly'][0]['turnover_cleaning'],50)
        self.assertEqual(base['monthly'][0]['maintenance'],m['monthly'][0]['maintenance'])
        self.assertIn('Excludes cleaning',next(c['includes'] for c in m['operating_costs'] if c['key']=='maintenance_pct'))

    def test_price_per_sqft_uses_purchase_price_not_asking(self):
        i=inputs();i['assumptions']['purchase_price']=300000
        m=analyse(i,{},'manual')
        self.assertAlmostEqual(m['metrics']['purchase_price_per_sqft'],464.52,places=2)
        i['property']['floor_area_sqm']=None
        self.assertIsNone(analyse(i,{},'manual')['metrics']['purchase_price_per_sqft'])

    def test_bid_ceiling_recalculates_tax_and_respects_fixed_loan(self):
        i=inputs();i['assumptions']['min_net_yield_pct']=6
        m=analyse(i,{},'manual');cap=m['purchase_guidance']['all_targets_price_ceiling']
        self.assertIsNotNone(cap)
        i['assumptions']['purchase_price']=cap
        self.assertTrue(all(t['passes'] for t in analyse(i,{},'manual')['tests']))
        i['assumptions']['purchase_price']=cap+1
        self.assertFalse(analyse(i,{},'manual')['tests'][0]['passes'])
        i['assumptions'].update(purchase_price=300000,financing='interest_only',mortgage_amount=270000)
        guide=analyse(i,{},'manual')['purchase_guidance']
        self.assertLess(guide['yield_price_ceiling'],270000)
        self.assertFalse(guide['feasible_with_current_finance'])
        self.assertIsNone(guide['all_targets_price_ceiling'])

    def test_configured_targets_not_fixed_six_percent(self):
        i=inputs();i['assumptions']['min_net_yield_pct']=3
        m=analyse(i,{},'manual')
        self.assertEqual(m['tests'][0]['target'],3)
        self.assertTrue(m['tests'][0]['passes'])


class ComparisonTests(unittest.TestCase):
    def test_eighteen_month_boundary_and_future_dates(self):
        self.assertEqual(months_ago(18,date(2026,8,31)),date(2025,2,28))
        self.assertTrue(recent_sale({'date':months_ago(18).isoformat()}))
        self.assertFalse(recent_sale({'date':(months_ago(18)-timedelta(days=1)).isoformat()}))
        self.assertFalse(recent_sale({'date':(date.today()+timedelta(days=1)).isoformat()}))

    def test_weak_sales_and_per_room_rent_do_not_establish_value(self):
        i=inputs();rows=[comp(j) for j in range(5)]
        rows[0]['bedrooms']=None;rows[1]['floor_area_sqm']=None;rows[2]['tenure']='leasehold'
        summary=comparison_summary(i,{'comparables':rows},'sold')
        self.assertEqual(summary['count'],2);self.assertIsNone(summary['range'])
        rents=[comp(j,'rent') for j in range(3)]
        for row in rents:row.update(source_id='research-test',rental_basis='per_room')
        self.assertIsNone(comparison_summary(i,{'comparables':rents},'rent')['median'])
        for row in rents:row['rental_basis']='whole_property_monthly'
        self.assertEqual(comparison_summary(i,{'comparables':rents},'rent')['median'],1520)

    def test_researched_rents_fill_blank_before_broad_average(self):
        i=inputs();i['assumptions']['monthly_rent']=None
        e={'comparables':[comp(j,'rent') for j in range(3)],'market':{'monthly_rent':700}}
        m=analyse(i,e,'manual')
        self.assertEqual(m['metrics']['monthly_rent'],1520)
        self.assertIn('matched',m['rent_basis'])

    def test_nullable_postcodes_and_dates_are_safe(self):
        row=comp(1,'rent');row.update(postcode=None,date=None,observed_at=None,distance=None)
        result=comparison_summary(inputs(),{'comparables':[row]},'rent')
        self.assertEqual(result['count'],0)
        self.assertTrue(result['candidates'][0]['limitations'])

    def test_asking_prices_show_mismatches_and_do_not_require_a_rental_basis(self):
        rows=[comp(j,'asking') for j in range(3)]
        for row in rows:row['source_id']='research-test'
        rows[0].update(bedrooms=2,distance=3,observed_at=None,date=None)
        summary=comparison_summary(inputs(),{'comparables':rows},'asking')
        self.assertEqual(summary['count'],2)
        self.assertEqual(summary['candidates'][-1]['address'],rows[0]['address'])
        self.assertIn('Bedrooms: 2 vs 6 in subject',summary['candidates'][-1]['limitations'])
        self.assertIn('For-sale listing is undated or over 90 days old',summary['candidates'][-1]['limitations'])
        self.assertFalse(any('rent' in reason.lower() for row in summary['candidates'] for reason in row['limitations']))


class ResearchTests(unittest.TestCase):
    def result(self):
        return {'sources':[{'id':'web-1','url':'https://council.gov.uk/map','title':'Official map','support':['Boundary record']}], 'text':'Evidence','queries':['map'],'errors':[]}

    def finding(self):
        return {'gap_id':'constraint.conservation_area','status':'supported','text':'Recorded inside the boundary','value_json':'true','source_ids':['web-1'],
                'matched_address':'12 Example Road, M1 1AA','matched_postcode':'M1 1AA','scope':'subject','evidence_date':date.today().isoformat(),'limitations':''}

    def test_exact_subject_and_native_citation_required(self):
        r=record();gap=[{'id':'constraint.conservation_area','provider_result':'Missing'}]
        f=self.finding();f['matched_address']='99 Other Road, M1 1AA'
        accepted=apply_findings(r,gap,self.result(),{'findings':[f]},1)
        self.assertEqual(accepted[0]['status'],'inconclusive');self.assertNotIn('constraint.conservation_area',r['evidence'].get('researched_facts',{}))
        f=self.finding();f['source_ids']=['invented']
        self.assertEqual(apply_findings(r,gap,self.result(),{'findings':[f]},1)[0]['status'],'inconclusive')
        self.assertEqual(apply_findings(r,gap,self.result(),{'findings':[self.finding()]},1)[0]['status'],'supported')
        self.assertTrue(r['evidence']['researched_facts']['constraint.conservation_area']['value'])

    def test_search_failure_not_reported_as_no_designation(self):
        r=record()
        with patch.dict('os.environ',{'ANTHROPIC_API_KEY':'test'}),patch('screening.narrative.choose_model',return_value='test'),patch('screening.research.web_search',side_effect=ValueError('Search unavailable')):
            research(r,'anthropic')
        self.assertEqual(r['evidence']['research']['status'],'partial_failure')
        self.assertTrue(all(f['status']=='failed' for f in r['evidence']['research']['findings']))
        self.assertFalse(r['evidence'].get('researched_facts'))

    def test_native_anthropic_citations_and_search_errors(self):
        raw={'stop_reason':'end_turn','content':[{'type':'server_tool_use','input':{'query':'test'}},{'type':'text','text':'Cited claim','citations':[{'url':'https://council.gov.uk/map','title':'Map','cited_text':'Evidence'}]},{'type':'web_search_tool_result','content':{'error_code':'max_uses_exceeded'}}]}
        with patch('screening.research.request_json',return_value=raw) as call:
            result=web_search('anthropic','key','model',{})
        self.assertEqual(result['sources'][0]['support'],['Evidence'])
        self.assertIn('max_uses_exceeded',result['errors'])
        self.assertIn('tools',call.call_args.kwargs['body'])

    def test_researched_fact_never_overwrites_client(self):
        r=record();r['evidence']['researched_facts']={'property.floor_area_sqm':{'value':100,'source_ids':['research-x'],'retrieved_at':'2026-10-24'}}
        self.assertEqual(enriched_inputs(r['inputs'],r['evidence'])['property']['floor_area_sqm'],60)
        r['inputs']['property']['floor_area_sqm']=None
        self.assertEqual(enriched_inputs(r['inputs'],r['evidence'])['property']['floor_area_sqm'],100)

    def test_unsupported_ai_numbers_and_no_silent_live_template(self):
        with self.assertRaises(ValueError):validate_figures({'summary':{'text':'Pay £999,999.99 now.'}},{'price':250000})
        validate_figures({'summary':{'text':'The price is £250,000.'}},{'price':250000})
        validate_figures({'summary':{'text':'Prices fell 2.1%.'}},{'observed_change_pct':-2.1})
        with self.assertRaises(ValueError):generate(record(),'none',strict=True)


class PDFTests(unittest.TestCase):
    def test_missing_rent_uses_same_ten_page_layout_and_all_exports(self):
        from screening.incomplete_report import generate_incomplete
        r=record();r['inputs']['assumptions']['monthly_rent']=None
        r['analysis']=analyse(r['inputs'],r['evidence'],'manual')
        content={'summary':{'text':'Research did not establish a usable rent; financial returns remain uncalculated.','source_ids':['model']},
                 'next_steps':[{'text':'Obtain a written whole-property rent opinion from a local letting agent.','source_ids':['model']}]}
        with tempfile.TemporaryDirectory() as folder,patch('screening.providers.request_json',side_effect=AssertionError('No API call for layout repair')):
            artifacts=generate_incomplete(r,'anthropic',folder)
            text=subprocess.check_output(['pdftotext',str(Path(folder)/artifacts['pdf']),'-'],text=True)
            self.assertTrue(artifacts['incomplete']);self.assertEqual(artifacts['page_count'],10)
            self.assertIn('cashflow_csv',artifacts);self.assertIn('cashflow_png',artifacts);self.assertIn('calculations_png',artifacts)
            self.assertIn('Financial results pending',' '.join(text.split()))
            self.assertIn('Not assessed',' '.join(text.split()))
            self.assertNotIn('Property evidence — assessment incomplete',text)

    def test_top_five_sales_full_reasoning_and_separate_sources(self):
        r=record();r['evidence']['comparables']=[comp(j) for j in range(8)]
        for j,row in enumerate(r['evidence']['comparables']):row['distance']=(j+1)/10
        r['evidence']['sources']=[{'id':'example','title':'EXTERNAL SOURCE REGISTER UNIQUE','url':'https://example.com/sales','status':'ok','retrieved_at':date.today().isoformat()}]
        r['analysis']=analyse(r['inputs'],r['evidence'],'manual');r['narrative']=deterministic(r)
        r['narrative']['content']['risks']=[{'text':'Evidence requires careful review. '*80+'UNTRUNCATED CONCLUSION END','source_ids':['model']}]
        with tempfile.TemporaryDirectory() as folder:
            artifacts=generate_report(r,folder)
            text=subprocess.check_output(['pdftotext',str(Path(folder)/artifacts['pdf']),'-'],text=True)
            sources=subprocess.check_output(['pdftotext',str(Path(folder)/artifacts['sources_pdf']),'-'],text=True)
            for j in range(5):self.assertIn(str(j+20)+' Example Road',text)
            self.assertNotIn('27 Example Road',text)
            self.assertIn('UNTRUNCATED CONCLUSION END',' '.join(text.split()))
            self.assertIn('EXTERNAL SOURCE REGISTER UNIQUE',sources)
            self.assertNotIn('EXTERNAL SOURCE REGISTER UNIQUE',text)
            self.assertIn('Purchase price per square foot',text)
            self.assertIn('Cleaning between tenancies',text)
            self.assertEqual(artifacts['page_count'],10)
            self.assertEqual(artifacts['sources_page_count'],1)
            self.assertFalse(artifacts['condensed'])

    def test_excessive_text_is_rejected_without_overwriting_or_extra_pages(self):
        r=record();r['analysis']=analyse(r['inputs'],r['evidence'],'manual');r['narrative']=deterministic(r)
        r['narrative']['content']['risks']=[{'text':'Evidence requires careful review. '*1000,'source_ids':['model']}]
        with tempfile.TemporaryDirectory() as folder:
            pdf=Path(folder)/'r1-draft.pdf';pdf.write_bytes(b'previous reviewed document')
            with self.assertRaisesRegex(ValueError,'fixed ten-page layout'):
                generate_report(r,folder)
            self.assertEqual(pdf.read_bytes(),b'previous reviewed document')

    def test_sources_only_include_cited_references_and_leave_logs_in_record(self):
        from screening.source_report import CitationIndex,generate_sources
        r=record();r['evidence']['sources']=[{'id':'used','title':'CITED SOURCE','url':'https://example.com/used','status':'ok'},
                                          {'id':'unused','title':'UNCITED SOURCE','url':'https://example.com/unused','status':'ok'},
                                          {'id':'duplicate','title':'DUPLICATE SOURCE','url':'https://example.com/used','status':'ok'}]
        r['evidence']['research']={'batches':[{'queries':['INTERNAL SEARCH LOG '*1000]}]}
        index=CitationIndex(r);index.markup('Evidence [used, duplicate]');r['report_citations']=index.used
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'sources.pdf';self.assertEqual(generate_sources(r,path),1)
            text=subprocess.check_output(['pdftotext',str(path),'-'],text=True)
            self.assertIn('CITED SOURCE',text);self.assertNotIn('UNCITED SOURCE',text)
            self.assertNotIn('INTERNAL SEARCH LOG',text);self.assertEqual(len(index.used),1)
            self.assertIn('INTERNAL SEARCH LOG',r['evidence']['research']['batches'][0]['queries'][0])

    def test_ten_pages_with_ten_gallery_photos_and_fifteen_year_horizon(self):
        from PIL import Image
        r=record();r['inputs']['assumptions']['holding_years']=15
        r['analysis']=analyse(r['inputs'],r['evidence'],'manual');r['narrative']=deterministic(r)
        with tempfile.TemporaryDirectory() as folder:
            Image.new('RGB',(160,100),'white').save(Path(folder)/'photo.jpg')
            r['photos']=[{'role':'cover' if j==0 else 'gallery','filename':'photo.jpg','caption':'Test photo','source':'Analyst'} for j in range(11)]
            artifacts=generate_report(r,folder)
            self.assertEqual(artifacts['page_count'],10)
            self.assertFalse(artifacts['condensed'])

if __name__=='__main__':unittest.main()
