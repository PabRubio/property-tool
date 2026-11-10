"""The approved design is a renderer contract, not a Bromley-only template."""
import copy
import importlib.util
import hashlib
import json
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch
from PIL import Image

from screening.reports import generate_report
from screening.store import Store
from test_lacewing_updates import build, pdf_text, pages


class SignatureReports(unittest.TestCase):
    def edit_heading(self,record,original,replacement):
        key=hashlib.sha256(('heading\0'+original).encode()).hexdigest()[:20]
        record.setdefault('presentation',{}).setdefault('text',{})[key]=replacement

    def test_wrapped_page_title_stays_above_subtitle(self):
        r=build()
        self.edit_heading(r,'Returns and growth','Returns and growth assumptions for the property and comparison of investment performance')
        with tempfile.TemporaryDirectory() as folder:
            a=generate_report(r,folder)
            xml=subprocess.check_output(['pdftotext','-f','2','-l','2','-bbox',str(Path(folder)/a['pdf']),'-'],text=True)
            words=[w for w in ET.fromstring(xml).iter() if w.tag.endswith('word')]
            title_end=next(float(w.attrib['yMax']) for w in words if w.text=='performance')
            subtitle_start=next(float(w.attrib['yMin']) for w in words if w.text=='Rental')
            self.assertLess(title_end,subtitle_start)

    def test_overwide_chart_heading_is_rejected_before_publication(self):
        r=build()
        title='Monthly cash before income tax · downside scenarios'
        self.edit_heading(r,title,title+' — detailed comparison of the investment assumptions and expected property performance')
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,'fixed ten-page layout'):
                generate_report(r,folder)
            self.assertEqual(list(Path(folder).iterdir()),[])

    def test_comparison_heading_edit_keeps_charts_and_tables(self):
        from test_report_evidence import comp
        from screening.finance import analyse
        r=build();r['evidence']['comparables']=[comp(1,'rent')]
        r['analysis']=analyse(r['inputs'],r['evidence'],r['mode'])
        self.edit_heading(r,'Top five completed sales — last 18 months','Recent completed sales')
        with tempfile.TemporaryDirectory() as folder:
            a=generate_report(r,folder)
            text=pdf_text(Path(folder)/a['pdf']).split('\f')[7]
            self.assertIn('Recent completed sales',text)
            self.assertIn('Advertised rents / month',text)

    def test_signature_layout_and_vector_cashflow_preserve_saved_analysis(self):
        record = build()
        analysis = copy.deepcopy(record['analysis'])
        with tempfile.TemporaryDirectory() as folder:
            artifacts = generate_report(record, folder)
            self.assertEqual(artifacts.get('report_style'), 'signature')
            self.assertEqual(artifacts['layout_version'], 5)
            path = Path(folder) / artifacts['pdf']
            self.assertEqual(pages(path), 10)
            text = pdf_text(path).split('\f')
            self.assertIn('The Signature Edition', text[0])
            self.assertIn('Ten-year annual cash-flow scenario', text[3])
            self.assertIn('First-year cash flow', text[3])
            self.assertIn('Rent due', text[3])
            self.assertIn('Monthly cash before income tax', text[4])
            self.assertIn('Known annual running-cost budgets', text[9])
            self.assertEqual(record['analysis'], analysis)
            prefix = Path(folder) / 'cover'
            subprocess.run(['pdftoppm', '-f', '1', '-l', '1', '-r', '72', '-singlefile',
                            '-png', str(path), str(prefix)], check=True, capture_output=True)
            im = Image.open(str(prefix) + '.png').convert('RGB')
            # Approved compact masthead, cream ground and tall split cover.
            self.assertEqual(im.getpixel((400, 20)), (1, 44, 33))
            self.assertEqual(im.getpixel((400, 50)), (246, 241, 230))
            self.assertEqual(im.getpixel((40, 400)), (1, 44, 33))
            self.assertEqual(im.getpixel((400, 600)), (228, 221, 205))

    def test_restyle_preserves_analysis_dates_exports_and_history(self):
        self.assertIsNotNone(importlib.util.find_spec('screening.restyle_reports'))
        from screening.restyle_reports import restyle_report
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder)
            r=store.create(build()['inputs'],'demo')
            r.update({key:value for key,value in build().items() if key not in ('id','revision')})
            r['artifacts']=generate_report(r,store.folder(r['id']))
            r['artifacts'].update(layout_version=4,generated_at='2026-02-03T12:00:00+00:00')
            r['artifacts'].pop('report_style',None)
            r['approval']={'reviewer':'Saved reviewer'}
            r['status']='approved'
            store.save(r)
            before=copy.deepcopy(store.load(r['id']))
            old_pdf=store.folder(r['id'])/r['artifacts']['pdf']
            old_bytes=old_pdf.read_bytes()
            with patch('screening.finance.analyse',side_effect=AssertionError('No recalculation')):
                self.assertTrue(restyle_report(store,r['id']))
            after=store.load(r['id'])
            for key in ('id','revision','inputs','analysis','narrative','evidence','photos','approval','status'):
                self.assertEqual(after[key],before[key],key)
            for key in ('generated_at','sources_pdf','internal_review_pdf','cashflow_csv','cashflow_png','calculations_png'):
                self.assertEqual(after['artifacts'][key],before['artifacts'][key],key)
            self.assertEqual(old_pdf.read_bytes(),old_bytes)
            self.assertEqual(after['report_citations'],before['report_citations'])
            snapshot=next((store.folder(r['id'])/'history').glob('before-signature-*.json'))
            self.assertEqual(json.loads(snapshot.read_text()),before)
            text=pdf_text(store.folder(r['id'])/after['artifacts']['pdf'])
            self.assertIn('2026-02-03',text)
            self.assertIn('2024-08-03',text)
            self.assertEqual(pages(store.folder(r['id'])/after['artifacts']['pdf']),10)
            self.assertFalse(restyle_report(store,r['id']))
            self.assertEqual(store.load(r['id']),after)

    def test_failed_restyle_keeps_current_report_and_record(self):
        self.assertIsNotNone(importlib.util.find_spec('screening.restyle_reports'))
        from screening.restyle_reports import restyle_report
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);r=store.create(build()['inputs'],'demo')
            r.update({key:value for key,value in build().items() if key not in ('id','revision')})
            r['artifacts']=generate_report(r,store.folder(r['id']))
            r['artifacts']['layout_version']=4
            store.save(r)
            before=(store.folder(r['id'])/'record.json').read_bytes()
            files=set(store.folder(r['id']).iterdir())
            with patch('screening.restyle_reports.render_report',side_effect=ValueError('fixed ten-page layout')):
                with self.assertRaisesRegex(ValueError,'fixed ten-page layout'):restyle_report(store,r['id'])
            self.assertEqual((store.folder(r['id'])/'record.json').read_bytes(),before)
            self.assertEqual(set(store.folder(r['id']).iterdir()),files)


if __name__ == '__main__':
    unittest.main()
