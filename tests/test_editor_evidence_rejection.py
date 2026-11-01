import copy
import json
import unittest
from unittest.mock import patch

from screening import edit_research
from test_report_evidence import record
from test_editor_research import findings_result, locality
from test_codex_research import scrape, bathroom


def locality_parts(r):
    entries=[];calls=[]
    for index,text in enumerate(('A supermarket serves Example Road.',
                                 'The local bus links Example Road and the city centre.',
                                 'The city station has direct trains to London.')):
        item,call=locality(r);url='https://operator.example/page-'+str(index)
        item.update(text=text,value_json=json.dumps(text),evidence_quote=text,source_ids=[url])
        payload={'success':True,'markdown':text,'metadata':{'sourceURL':url}}
        call.update(arguments={'url':url},result={'structuredContent':payload})
        entries.append(item);calls.append(call)
    return entries,calls


class EditorEvidenceRejection(unittest.TestCase):
    def test_all_individually_cited_locality_fragments_survive(self):
        r=record();items,calls=locality_parts(r)
        edit_research.apply(r,findings_result(items,calls))
        fact=r['evidence']['researched_facts']['property.nearby_places']
        for item in items:self.assertIn(item['text'],fact['value'])
        self.assertEqual(len(fact['source_ids']),3)
        self.assertLessEqual(len(fact['value'].split()),65)
        stored=r['evidence']['research']['findings']
        self.assertEqual(len(stored),1)
        self.assertEqual(len(stored[0]['supporting_findings']),3)

    def test_invalid_second_fragment_cannot_hide_behind_valid_first_fragment(self):
        r=record();before=copy.deepcopy(r);items,calls=locality_parts(r)
        items[1]['evidence_quote']='Invented bus service without any observed support.'
        with self.assertRaisesRegex(ValueError,'nearby|amenities'):
            edit_research.apply(r,findings_result(items,calls))
        self.assertEqual(r,before)

    def test_duplicate_subject_facts_fail_instead_of_silently_selecting_first(self):
        r=record();one=bathroom(r);two=dict(one,value_json='3')
        with self.assertRaisesRegex(ValueError,'Duplicate|duplicate'):
            edit_research.apply(r,findings_result([one,two],[scrape()]))

    def test_locality_overflow_returns_budget_feedback(self):
        r=record();items,calls=locality_parts(r)
        for i,item in enumerate(items):item['value_json']=json.dumps(str(i)+' '+' '.join(['Nearby']*30))
        with self.assertRaisesRegex(ValueError,'65'):
            edit_research.apply(r,findings_result(items,calls))

    def test_one_tool_free_repair_uses_captured_pages_and_revalidates(self):
        self.assertTrue(hasattr(edit_research,'apply_with_repair'),'No bounded citation correction exists')
        r=record();original=copy.deepcopy(r['inputs']);item,call=locality(r)
        bad=dict(item,evidence_quote='Wrong quoted wording missing from the page.')
        fixed=findings_result([item],[call])
        with patch('screening.codex.run',return_value=fixed) as run:
            audit=edit_research.apply_with_repair(r,findings_result([bad],[call]),'Add amenities')
        self.assertEqual(run.call_count,1)
        self.assertFalse(run.call_args.kwargs.get('research',False))
        self.assertEqual(run.call_args.kwargs['timeout'],60)
        self.assertTrue(run.call_args.args[1]['observed_sources'])
        self.assertTrue(run.call_args.args[1]['validation_feedback'])
        self.assertTrue(audit['corrected'])
        self.assertEqual(r['inputs'],original)

    def test_invalid_repair_stops_and_preserves_the_rejected_response(self):
        self.assertTrue(hasattr(edit_research,'apply_with_repair'),'No bounded citation correction exists')
        r=record();before=copy.deepcopy(r);item,call=locality(r)
        bad=dict(item,evidence_quote='Wrong quoted wording missing from the page.')
        reply=findings_result([bad],[call])
        with patch('screening.codex.run',return_value=reply) as run:
            with self.assertRaises(ValueError) as caught:
                edit_research.apply_with_repair(r,reply,'Add amenities')
        self.assertEqual(run.call_count,1)
        self.assertEqual(r,before)
        self.assertEqual(caught.exception.research_result['output'],reply['output'])
        self.assertTrue(caught.exception.feedback)

    def test_malformed_correction_retains_the_actual_final_response(self):
        r=record();item,call=locality(r)
        item['evidence_quote']='Wrong quotation that is not on the page.'
        malformed={'wrong':'unexpected correction format'}
        with patch('screening.codex.run',return_value={'output':malformed}):
            with self.assertRaises(ValueError) as caught:
                edit_research.apply_with_repair(r,findings_result([item],[call]),'Add amenities')
        self.assertEqual(caught.exception.research_result['output'],malformed)

    def test_empty_correction_after_unobserved_claim_is_not_success(self):
        r=record();before=copy.deepcopy(r);item,_=locality(r)
        with patch('screening.codex.run',return_value=findings_result()) as run:
            with self.assertRaisesRegex(ValueError,'No supported|no supported'):
                edit_research.apply_with_repair(r,findings_result([item],[]),'Add amenities')
        self.assertEqual(run.call_count,1)
        self.assertEqual(r,before)


if __name__=='__main__':unittest.main()
