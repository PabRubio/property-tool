"""Offline commercial report, editor and companion export contracts."""
import copy
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from screening.finance import analyse
from screening.narrative import deterministic, generate, plan_revision
from screening.preflight import correct, assess
from screening.reports import generate_report
from screening.schema import validate
from screening.source_report import references
from screening.tax_notes import tax_explanation
from test_commercial import commercial_brief
from test_lacewing_updates import pdf_text, pages


def commercial_record(changes=None):
    data = commercial_brief('offices')
    data['property'].update(use_class='Class E', repair_responsibility='tenant', insurance_responsibility='tenant')
    data['assumptions'].update(legal_fees=1500, survey_fees=1000)
    data['assumptions'].update(changes or {})
    inputs = validate(data)
    evidence = {'asset_class':'commercial', 'sources':[
        {'id':'rents-commercial','title':'Commercial quoting rents','url':'https://example.com/rents','status':'ok'},
        {'id':'valuation-commercial-rent','title':'Commercial rent estimate','url':'https://example.com/rent','status':'ok'},
        {'id':'valuation-commercial-sale','title':'Commercial capitalisation estimate','url':'https://example.com/sale','status':'ok'}],
        'market':{'rents-commercial':{'points_analysed':42,'unit_type':'NIA','avg_quoting_rent_per_sqft':45,'avg_quoting_rent':96750}},
        'comparables':[]}
    record = {'id':'c'*32,'revision':1,'mode':'manual','inputs':inputs,'evidence':evidence,'photos':[]}
    record['analysis'] = analyse(inputs, evidence, 'manual')
    record['narrative'] = deterministic(record)
    return record


class CommercialReportTests(unittest.TestCase):
    def test_ten_pages_describe_commercial_area_lease_market_and_vat(self):
        r = commercial_record({'purchase_vat_pct':20,'purchase_vat_recoverable_pct':100,'vat_recovery_month':3,
                               'break_month':24,'rent_review_month':12,'rent_review_annual_rent':30000})
        before = copy.deepcopy(r['analysis'])
        with tempfile.TemporaryDirectory() as folder:
            artifacts = generate_report(r, folder)
            text = pdf_text(Path(folder)/artifacts['pdf'])
            self.assertEqual(pages(Path(folder)/artifacts['pdf']),10)
            self.assertEqual(artifacts['report_style'],'signature')
            labels={item['original'] for item in r['report_document'].values()}
            self.assertFalse(any('habitable rooms' in label for label in labels))
            self.assertIn('Net project cost + recoverable VAT - loan + fees + reserve',labels)
            for expected in ('NIA','Class E','Occupancy','Tenant lease','Quoting','Purchase VAT','VAT recovery','Business rates','24'):
                self.assertIn(expected,text)
            for forbidden in ('Bedrooms:','habitable rooms','per-room/HMO','Local historical prices','Nearby activity','Residential finance-cost','ATED'):
                self.assertNotIn(forbidden,text)
            with (Path(folder)/artifacts['cashflow_csv']).open(encoding='utf-8-sig') as stream:
                rows=list(csv.DictReader(stream))
            first=[row for row in rows if row['holding_years']=='5']
            self.assertEqual(sum(float(row['vat_recovery']) for row in first),55000)
            self.assertEqual(pages(Path(folder)/artifacts['sources_pdf']),1)
            internal=pdf_text(Path(folder)/artifacts['internal_review_pdf'])
            self.assertIn('tenant covenant',internal.lower())
        self.assertEqual(r['analysis'],before)

    def test_incomplete_commercial_report_keeps_facts_and_withholds_exports(self):
        r = commercial_record({'purchase_vat_pct':None})
        with tempfile.TemporaryDirectory() as folder:
            artifacts=generate_report(r,folder)
            text=pdf_text(Path(folder)/artifacts['pdf'])
            self.assertTrue(artifacts['incomplete'])
            self.assertEqual(pages(Path(folder)/artifacts['pdf']),10)
            self.assertNotIn('cashflow_csv',artifacts)
            self.assertIn('purchase_vat_pct',text)
            self.assertIn('Tenant lease',text)
            self.assertNotIn('Bedrooms:',text)

    def test_incomplete_writer_preserves_commercial_missing_terms(self):
        from screening.incomplete_report import generate_incomplete
        r=commercial_record({'lease_remaining_months':None})
        content={'summary':{'text':'The tenant lease remaining term is unconfirmed; dependent returns are unavailable.','source_ids':['model']},
                 'next_steps':[{'text':'Obtain the actual tenant lease and verify remaining term and break dates.','source_ids':['inputs']}]}
        with tempfile.TemporaryDirectory() as folder, patch('screening.incomplete_report.call_model',return_value=content) as model:
            artifacts=generate_incomplete(r,'codex',folder)
            text=pdf_text(Path(folder)/artifacts['pdf'])
            internal=pdf_text(Path(folder)/artifacts['internal_review_pdf'])
        self.assertTrue(artifacts['incomplete'])
        self.assertIn('lease_remaining_months',text)
        self.assertIn('actual tenant lease',internal)
        self.assertIn('COMMERCIAL SCOPE',model.call_args.args[2])

    def test_tax_notes_and_register_exclude_residential_tax_rules(self):
        r=commercial_record()
        for buyer in ('individual','company'):
            a=dict(r['analysis']['effective_assumptions'],buyer_type=buyer)
            text=tax_explanation(a)
            self.assertIn('non-residential',text)
            self.assertIn('VAT',text)
            self.assertNotIn('ATED',text)
            self.assertNotIn('basic-rate tax reduction',text)
        refs={source['id']:source for source in references(r)}
        self.assertNotIn('tax-finance',refs)
        self.assertNotIn('tax-ated',refs)
        self.assertEqual(refs['tax-vat']['retrieved_at'],'2026-11-12')
        self.assertIn('empty-property-relief',refs['tax-rates']['url'])

    def test_explicit_single_rent_correction_updates_both_units(self):
        for field,value,annual,monthly in [('annual_rent',30000,30000,2500),('monthly_rent',3000,36000,3000),('annual_rent','30000',30000,2500),('monthly_rent',None,None,None)]:
            inputs=commercial_record()['inputs']
            output={'changes':[{'section':'assumptions','key':field,'value':value}],'message':'Rent corrected.'}
            with patch('screening.preflight.call_model',return_value=output):
                result,changes,_=correct(inputs,'Correct the agreed rent.','codex')
            self.assertEqual(result['assumptions']['annual_rent'],annual)
            self.assertEqual(result['assumptions']['monthly_rent'],monthly)
            self.assertEqual(len(changes),1)

    def test_conflicting_explicit_rent_corrections_still_rejected(self):
        output={'changes':[{'section':'assumptions','key':'annual_rent','value':30000},
                           {'section':'assumptions','key':'monthly_rent','value':3000}],'message':'Rent corrected.'}
        with patch('screening.preflight.call_model',return_value=output), self.assertRaisesRegex(ValueError,'annual.*monthly|Annual.*monthly'):
            correct(commercial_record()['inputs'],'Correct rent.','codex')

    def test_editor_accepts_commercial_fields_and_syncs_rent(self):
        r=commercial_record()
        changes=[{'section':'assumptions','key':'annual_rent','value':36000},
                 {'section':'property','key':'floor_area_basis','value':'nia'}]
        result={'can_apply':True,'message':'Updated','changes':changes,'text_edits':[], 'style_changes':[],
                'page_order':None,'rewrite_commentary':True,'research':{}}
        replies=[{'output':result,'tool_calls':[],'model':'test'}, {'output':{'changes':changes},'tool_calls':[],'model':'test'}]
        with patch('screening.codex.run',side_effect=replies) as run:
            updated,*_=plan_revision(r,'codex','The annual rent is £36,000; floor area is NIA.')
        self.assertEqual(updated['assumptions']['monthly_rent'],3000)
        packet=run.call_args_list[0].args[1]
        self.assertIn('offices',packet['input_choices']['property_type'])
        self.assertIn('commercial',packet['input_choices']['asset_class'])
        self.assertIn('COMMERCIAL SCOPE',run.call_args_list[0].args[0])

    def test_writer_and_preflight_receive_commercial_scope(self):
        r=commercial_record()
        content=copy.deepcopy(r['narrative']['content']);content['risks']=content['risks'][:5]
        with patch('screening.narrative.call_model',return_value=content) as model:
            generate(r,'codex',strict=True)
        system=model.call_args.args[2]
        self.assertIn('COMMERCIAL SCOPE',system)
        self.assertIn('lease',system)
        with patch('screening.preflight.call_model',return_value={'summary':'No concerns.','issues':[]}) as model:
            self.assertEqual(assess(r['inputs'],'codex')['status'],'clear')
        self.assertIn('COMMERCIAL SCOPE',model.call_args.args[2])
