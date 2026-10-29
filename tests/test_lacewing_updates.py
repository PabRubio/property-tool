"""Offline checks for financial dependencies, fixed PDFs and transactional edits."""
import copy
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from app import create_app, provenance
from screening.schema import validate_submission
from screening.finance import analyse
from screening.narrative import deterministic
from screening.reports import generate_report
from screening.comparisons import comparison_summary
from test_intake import brief
from test_report_evidence import comp


def build(payload=None):
    payload=payload or brief()
    inputs=provenance(validate_submission(payload),supplied=payload)
    r={'id':'a'*32,'revision':1,'mode':'demo','inputs':inputs,'evidence':{'sources':[],'comparables':[]},'photos':[]}
    r['analysis']=analyse(inputs,r['evidence'],'demo');r['narrative']=deterministic(r)
    return r


def pdf_text(path):
    return subprocess.check_output(['pdftotext','-layout',str(path),'-'],text=True)


def pages(path):
    return int(next(line.split(':')[1].strip() for line in subprocess.check_output(['pdfinfo',str(path)],text=True).splitlines() if line.startswith('Pages:')))


class ModelUpdates(unittest.TestCase):
    def test_management_strategy_and_explicit_overrides(self):
        for notes,expected in [('',14.4),('Established HMO letting',18),('Existing student letting arrangement',18),('Possible HMO conversion',14.4),('Not an HMO',14.4)]:
            b=brief();b['investor']['notes']=notes
            self.assertEqual(build(b)['analysis']['effective_assumptions']['management_pct'],expected)
        b['investor']['notes']='Established HMO';b['assumptions']['management_pct']=12
        self.assertEqual(build(b)['analysis']['effective_assumptions']['management_pct'],12)
        b['assumptions']['management_pct']=14.4
        self.assertEqual(build(b)['analysis']['effective_assumptions']['management_pct'],14.4)

    def test_funding_does_not_change_financial_tests_or_bid_ceiling(self):
        b=brief();b['investor']['cash_budget']=0;m=build(b)['analysis']
        self.assertEqual(len(m['tests']),2);self.assertGreater(m['funding']['shortfall'],0)
        self.assertEqual(m['funding']['initial_shortfall'],m['funding']['cash_required'])
        b['investor']['cash_budget']=1000000;n=build(b)['analysis']
        self.assertEqual(n['funding']['initial_shortfall'],0)
        self.assertEqual(m['tests'],n['tests'])
        self.assertEqual(m['purchase_guidance']['all_targets_price_ceiling'],n['purchase_guidance']['all_targets_price_ceiling'])

    def test_safety_counted_once_and_explicit_costs_preserved(self):
        b=brief();base=build(b)['analysis'];b['assumptions'].update(safety_upfront=800,compliance=450)
        m=build(b)['analysis']
        self.assertEqual(m['metrics']['cash_required']-base['metrics']['cash_required'],650)
        self.assertAlmostEqual(base['metrics']['stabilised_noi']-m['metrics']['stabilised_noi'],200,places=2)
        b['assumptions'].update(safety_included_in='other_purchase_costs',other_purchase_costs=800)
        n=build(b)['analysis']
        self.assertEqual(n['metrics']['cash_required'],m['metrics']['cash_required'])
        self.assertEqual(n['effective_assumptions']['safety_upfront'],0)

    def test_works_value_separate_from_market_growth(self):
        b=brief();b['assumptions'].update(refurb_level='refurb_light',refurbishment=20000,price_growth_pct=0)
        m=build(b)['analysis']
        self.assertEqual(m['refurbishment_value']['uplift'],10000)
        self.assertEqual(m['exit']['sale_price'],260000)
        b['assumptions'].update(after_works_value=290000,after_works_source='Investor supplied survey scenario')
        n=build(b)['analysis'];self.assertEqual(n['refurbishment_value']['uplift'],40000)
        self.assertEqual(n['exit']['sale_price'],290000)
        self.assertEqual(n['metrics']['cash_required'],m['metrics']['cash_required'])

    def test_partial_dependencies(self):
        b=brief();b['assumptions']['monthly_rent']=None;m=build(b)['analysis']
        self.assertFalse(m['available']);self.assertEqual(m['metrics']['purchase_price'],250000)
        self.assertGreater(m['metrics']['cash_required'],250000);self.assertIsNone(m['metrics']['gross_yield_pct'])
        self.assertEqual(m['horizons'][0]['exit']['sale_price'],250000)
        self.assertIsNotNone(m['horizons'][0]['exit']['sale_proceeds'])
        self.assertIsNone(m['horizons'][0]['exit']['annual_irr_pct'])
        b=brief();b['property'].update(asking_price=None,price_status='unknown');m=build(b)['analysis']
        self.assertEqual(m['metrics']['monthly_rent'],1520);self.assertGreater(m['metrics']['stabilised_noi'],0)
        self.assertIsNone(m['metrics']['cash_required']);self.assertIsNone(m['metrics']['net_yield_on_cost_pct'])
        b=brief();b['assumptions'].update(refurb_level='refurb_light',refurbishment=None);m=build(b)['analysis']
        self.assertFalse(m['available']);self.assertIsNone(m['metrics']['refurbishment_with_contingency'])
        self.assertIsNone(m['metrics']['total_property_cost']);self.assertIsNotNone(m['metrics']['monthly_cashflow_before_tax'])

    def test_comparison_ranking_nearest_bedrooms_before_distance(self):
        r=build();rows=[comp(j,'rent') for j in range(5)]
        for j,row in enumerate(rows):row.update(bedrooms=j+2,distance=(6-j)/10)
        rows[0]['distance']=.01
        result=comparison_summary(r['inputs'],{'comparables':rows},'rent')['candidates']
        self.assertEqual([r['bedrooms'] for r in result],[6,5,4,3,2])
        rows[4].update(rental_basis='per_room',source_id='rents')
        result=comparison_summary(r['inputs'],{'comparables':rows},'rent')
        self.assertTrue(any('Whole-property' in gap for gap in result['candidates'][0]['limitations']))

    def test_same_completed_sale_merges_town_and_comma_variants(self):
        r=build();rows=[comp(j,'sold') for j in range(3)]
        rows[0].update(address='7, Friars Row',postcode='DH1 1HF',amount=325000)
        rows[1].update(address='7 Friars Row, Durham DH1 1HF',postcode='DH1 1HF',amount=325000)
        rows[2].update(address='8 Friars Row, Durham DH1 1HF',postcode='DH1 1HF',amount=325000)
        result=comparison_summary(r['inputs'],{'comparables':rows},'sold')['candidates']
        self.assertEqual(len(result),2)
        merged=next(row for row in result if row['address'].startswith('7 '))
        self.assertEqual(set(merged['evidence_urls']),{rows[0]['source_url'],rows[1]['source_url']})


class ReportUpdates(unittest.TestCase):
    def test_cover_move_internal_content_and_links(self):
        r=build();r['evidence']['comparables']=[comp(j,'asking') for j in range(5)]
        r['analysis']=analyse(r['inputs'],r['evidence'],'demo')
        verdict='The complete verdict paragraph remains intact and conditional on the stated model.'
        r['narrative']['content']['summary']={'text':verdict,'source_ids':['inputs','model']}
        investigation='Costs are incomplete. Obtain cleaning quotes and resolve the price evidence.'
        r['narrative']['content']['risks']=[{'text':investigation,'source_ids':['inputs']}]
        with tempfile.TemporaryDirectory() as folder:
            a=generate_report(r,folder);main=pdf_text(Path(folder)/a['pdf']).split('\f')
            self.assertNotIn('Investment overview',main[0]);self.assertIn('Investment overview',main[1]);self.assertIn(verdict,' '.join(main[1].split()))
            self.assertIn('Figures depend on the stated rent',main[1]);self.assertIn('Location and nearby amenities',main[0])
            self.assertIn('Property screening',main[0]);self.assertNotIn('Property introduction',main[0])
            self.assertEqual(main[0].count(r['inputs']['property']['address']),1)
            self.assertNotIn(investigation,' '.join(''.join(main).split()))
            internal=subprocess.check_output(['pdftotext',str(Path(folder)/a['internal_review_pdf']),'-'],text=True)
            self.assertIn(investigation,' '.join(internal.split()))
            for key,count in [('pdf',10),('sources_pdf',1),('internal_review_pdf',1)]:self.assertEqual(pages(Path(folder)/a[key]),count)
            xml=subprocess.check_output(['pdftohtml','-i','-xml','-stdout',str(Path(folder)/a['pdf'])],text=True)
            self.assertIn('google.com/maps/search',xml)
            sources=subprocess.check_output(['pdftohtml','-i','-xml','-stdout',str(Path(folder)/a['sources_pdf'])],text=True)
            self.assertIn('https://example.com/property/0',sources)

    def test_draft_ten_slots_final_only_uploaded_photos(self):
        with tempfile.TemporaryDirectory() as folder:
            r=build();a=generate_report(r,folder);text=pdf_text(Path(folder)/a['pdf'])
            self.assertNotIn('Additional photo ',text)
            photo_text=subprocess.check_output(['pdftotext','-raw',str(Path(folder)/a['pdf']),'-'],text=True)
            for i in range(1,11):self.assertIn('Photo '+str(i)+' — not supplied',' '.join(photo_text.split()))
            self.assertIn('Property photograph not supplied',text)
            for i in range(3):
                filename='photo-%s.jpg'%i;Image.new('RGB',(300,200),(i*80,100,130)).save(Path(folder)/filename)
                r['photos'].append({'filename':filename,'role':'cover' if i==0 else 'gallery','source':'Test fixture'})
            a=generate_report(r,folder,final=True);text=pdf_text(Path(folder)/a['pdf'])
            self.assertNotIn('not supplied',text[text.index('Property photographs'):text.index('Sale history and nearby market')])
            self.assertNotIn('Property photograph not supplied',text)
            self.assertEqual(pages(Path(folder)/a['pdf']),10)
            images=subprocess.check_output(['pdfimages','-list',str(Path(folder)/a['pdf'])],text=True)
            photo_pages=[line.split()[0] for line in images.splitlines()[2:] if line.split()[3:5]==['300','200']]
            self.assertEqual(photo_pages,['1','6','6'])

    def test_missing_inputs_keep_ten_pages(self):
        for missing in ['monthly_rent','asking_price','refurbishment']:
            b=brief()
            if missing=='asking_price':b['property'].update(asking_price=None,price_status='unknown')
            elif missing=='refurbishment':b['assumptions'].update(refurb_level='refurb_light',refurbishment=None)
            else:b['assumptions'][missing]=None
            with self.subTest(missing=missing),tempfile.TemporaryDirectory() as folder:
                r=build(b);a=generate_report(r,folder)
                self.assertEqual(pages(Path(folder)/a['pdf']),10);self.assertTrue(a['incomplete'])
                self.assertIn('Not available',pdf_text(Path(folder)/a['pdf']))

    def test_companion_failure_keeps_every_previous_artifact(self):
        with tempfile.TemporaryDirectory() as folder:
            r=build();a=generate_report(r,folder)
            before={key:(Path(folder)/a[key]).read_bytes() for key in ('pdf','sources_pdf','internal_review_pdf','cashflow_csv','cashflow_png','calculations_png')}
            with patch('screening.internal_review.generate_internal',side_effect=ValueError('Internal review too long')):
                with self.assertRaises(ValueError):generate_report(r,folder)
            self.assertEqual(before,{key:(Path(folder)/a[key]).read_bytes() for key in before})


class EditUpdates(unittest.TestCase):
    def wait_job(self,app,id):
        for _ in range(500):
            r=app.store.load(id)
            if r.get('job',{}).get('state') in ('done','failed'):return r
            time.sleep(.01)
        self.fail('Job timed out')

    def test_success_refreshes_exports_and_failed_edit_keeps_working_report(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict('os.environ',{'ANTHROPIC_API_KEY':'test'}):
            app=create_app(folder);client=app.test_client();headers={'X-Local-Token':app.csrf_token}
            r=app.store.create(build()['inputs'],'demo');r.update(analysis=analyse(r['inputs'],r['evidence'],'demo'))
            r['narrative']=deterministic(r);r['artifacts']=generate_report(r,app.store.folder(r['id']));r['status']='ready_for_review';app.store.save(r)
            old=copy.deepcopy(r);new=copy.deepcopy(r['inputs']);new['assumptions']['monthly_rent']=1800
            planned=(new,'Rent updated',[{'section':'assumptions','key':'monthly_rent','value':1800}],{},True)
            with patch('app.plan_revision',return_value=planned),patch('app.generate',side_effect=lambda r,p,**kw:deterministic(r)):
                response=client.post('/api/records/'+r['id']+'/revise',json={'revision':r['revision'],'provider':'anthropic','instruction':'Rent 1800'},headers=headers)
                self.assertEqual(response.status_code,202);r=self.wait_job(app,r['id'])
            self.assertEqual(r['job']['state'],'done',r['job']);self.assertEqual(r['analysis']['metrics']['monthly_rent'],1800)
            self.assertNotEqual(r['artifacts']['pdf'],old['artifacts']['pdf'])
            with client.get('/api/records/'+r['id']+'/download/cashflow_csv') as response:self.assertIn(b'1800.0',response.data)
            for kind in ('pdf','sources_pdf','internal_review_pdf','calculations_png','cashflow_csv','json'):
                with client.get('/api/records/'+r['id']+'/download/'+kind) as response:self.assertEqual(response.status_code,200)
            before=copy.deepcopy(r)
            with patch('app.plan_revision',side_effect=ValueError('Mocked writing failure')):
                client.post('/api/records/'+r['id']+'/revise',json={'revision':r['revision'],'provider':'anthropic','instruction':'Fail'},headers=headers)
                r=self.wait_job(app,r['id'])
            self.assertEqual(r['artifacts'],before['artifacts']);self.assertEqual(r['analysis'],before['analysis'])
            self.assertEqual(r['revision'],before['revision'])
            with patch('app.generate',side_effect=ValueError('Mocked generation failure')):
                client.post('/api/records/'+r['id']+'/analyse',json={'revision':r['revision'],'provider':'none'},headers=headers)
                r=self.wait_job(app,r['id'])
            self.assertEqual(r['artifacts'],before['artifacts']);self.assertEqual(r['analysis'],before['analysis'])
