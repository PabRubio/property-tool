"""Research controller regressions; external Codex/Firecrawl calls are simulated."""
import copy
import json
import unittest
from unittest.mock import patch

from screening import codex_research
from screening.providers import now
from test_report_evidence import record
from test_codex_research import bathroom, scrape, URL


AUGUST = 'https://fees.example/2026/08/current.docx'
JULY = 'https://fees.example/2026/07/old.pdf'


def action(target=AUGUST, tool='firecrawl_scrape', purpose='Read the latest August fee schedule'):
    return dict(tool=tool, target=target, purpose=purpose)


def result(calls=None, followups=None, findings=None, done=True):
    return {'output': {'findings': findings or [], 'estimates': [], 'cost_estimates': [],
                       'next_searches': followups or [], 'done': done, 'summary': 'Checked available leads.'},
            'tool_calls': calls or [], 'model': 'test'}


def call_for(task, failed=False, text='A successfully read fee schedule.'):
    key='query' if task['tool']=='firecrawl_search' else 'url'
    payload={'success':True,'data':[]} if key=='query' else {'success':True,'markdown':text,'metadata':{'sourceURL':task['target']}}
    return {'type':'mcpToolCall','server':'firecrawl','tool':task['tool'],
            'status':'failed' if failed else 'completed','arguments':{key:task['target']},
            'result':{'content':[{'type':'text','text':text if failed else json.dumps(payload)}]}}


def with_locality():
    r=record()
    r['evidence']['sources']=[{'id':'locality','status':'ok','url':'https://council.example/transport'}]
    r['evidence']['researched_facts']={'property.nearby_places':{
        'value':'Existing cited locality context.', 'source_ids':['locality'],'retrieved_at':now()}}
    return r


class ResearchFollowups(unittest.TestCase):
    def test_missing_amenities_is_the_first_action_and_is_actually_attempted(self):
        r=record();original=copy.deepcopy(r['inputs']);seen=[]
        def respond(system, packet, schema, **kwargs):
            task=packet.get('priority_follow_up')
            self.assertIsNotNone(task, 'Missing locality must receive a concrete first task')
            self.assertEqual(task['id'],'amenities')
            self.assertIn('M1 1AA',task['target'])
            seen.append(task)
            return result(calls=[call_for(task)])
        with patch('screening.codex_research.run',side_effect=respond):codex_research.research(r)
        self.assertEqual(r['inputs'],original)
        self.assertEqual(r['evidence']['research']['follow_ups'][0]['status'],'checked')
        self.assertEqual(len(seen),1)
        self.assertIn('property.nearby_places',r['evidence']['research']['unresolved'])

    def test_august_followup_survives_omission_and_premature_done(self):
        r=with_locality();seen=[]
        def respond(system,packet,schema,**kwargs):
            seen.append(copy.deepcopy(packet))
            if len(seen)==1:return result(followups=[action()])
            if len(seen)==2:return result()  # task forgotten in this response
            task=packet['priority_follow_up']
            return result(calls=[call_for(task)])
        with patch('screening.codex_research.run',side_effect=respond):codex_research.research(r)
        self.assertEqual(len(seen),3)
        self.assertEqual(seen[2]['priority_follow_up']['target'],AUGUST)
        self.assertEqual(r['evidence']['research']['follow_ups'][0]['status'],'checked')

    def test_tasks_progress_beyond_soft_target_without_new_property_facts(self):
        r=with_locality();clock=[0];packets=[]
        def respond(system,packet,schema,**kwargs):
            packets.append(copy.deepcopy(packet));clock[0]+=110
            if len(packets)==1:return result(followups=[action(),action('https://council.example/buses',purpose='Read local bus links')],done=False)
            if len(packets)==2:return result(done=False)
            return result(calls=[call_for(packet['priority_follow_up'])])
        with patch('screening.codex_research.time.monotonic',side_effect=lambda:clock[0]), patch('screening.codex_research.run',side_effect=respond):
            codex_research.research(r)
        self.assertEqual(len(packets),4)
        self.assertGreater(r['evidence']['research']['elapsed_seconds'],300)
        self.assertTrue(all(x['status']=='checked' for x in r['evidence']['research']['follow_ups']))

    def test_already_attempted_duplicate_action_is_not_requeued(self):
        r=with_locality();lead=action();calls=[call_for(lead)]
        with patch('screening.codex_research.run',return_value=result(calls=calls,followups=[lead,dict(lead,purpose='Check same fees again')])) as run:
            codex_research.research(r)
        self.assertEqual(run.call_count,1)
        self.assertEqual(len(r['evidence']['research']['follow_ups']),1)
        self.assertEqual(r['evidence']['research']['follow_ups'][0]['status'],'checked')

    def test_failed_page_is_recorded_unavailable_not_a_resolved_fact(self):
        r=with_locality();lead=action()
        with patch('screening.codex_research.run',side_effect=[result(followups=[lead]),result(calls=[call_for(lead,failed=True,text='Document format not supported')])]):
            codex_research.research(r)
        task=r['evidence']['research']['follow_ups'][0]
        self.assertEqual(task['status'],'unavailable')
        self.assertTrue(task['reason'])
        self.assertFalse(r['evidence'].get('cost_estimates'))

    def test_real_quota_preserves_findings_and_is_not_cached_as_completed(self):
        r=with_locality();quota=call_for(action('local survey fees','firecrawl_search'),failed=True,
                                      text="Firecrawl's daily limit without an account was reached.")
        reply=result(calls=[scrape(),quota],findings=[bathroom(r)],followups=[action()])
        with patch('screening.codex_research.run',return_value=reply) as run:
            codex_research.research(r)
            self.assertEqual(r['evidence']['research']['status'],'limited')
            self.assertIn('Firecrawl',r['evidence']['research']['stop_reason'])
            self.assertEqual(r['evidence']['researched_facts']['property.bathrooms']['value'],2)
            codex_research.research(r)
        self.assertEqual(run.call_count,2)

    def test_quota_words_in_successful_page_are_not_a_tool_failure(self):
        r=with_locality()
        with patch('screening.codex_research.run',return_value=result(calls=[scrape('Article: daily limit, quota exceeded and rate limit are examples of software errors.')])):
            codex_research.research(r)
        self.assertEqual(r['evidence']['research']['status'],'completed')

    def test_hard_deadline_retains_unfinished_tasks_and_records_interruption(self):
        r=with_locality();clock=[0];timeouts=[]
        def respond(system,packet,schema,**kwargs):
            timeouts.append(kwargs['timeout']);clock[0]+=120
            return result(followups=[action()],done=False)
        with patch('screening.codex_research.time.monotonic',side_effect=lambda:clock[0]), patch('screening.codex_research.run',side_effect=respond):
            codex_research.research(r)
        audit=r['evidence']['research']
        self.assertEqual(audit['status'],'partial_failure')
        self.assertEqual(audit['elapsed_seconds'],600)
        self.assertEqual(audit['follow_ups'][0]['status'],'pending')
        self.assertLessEqual(max(timeouts),180)
        self.assertEqual(timeouts[-1],120)

    def test_dead_ends_still_stop_when_no_concrete_followups_remain(self):
        r=with_locality()
        with patch('screening.codex_research.run',return_value=result(done=False)) as run:codex_research.research(r)
        self.assertEqual(run.call_count,2)
        self.assertEqual(r['evidence']['research']['stop_reason'],'No useful progress in two rounds')

    def test_retry_retains_pending_tasks_and_history_after_accepting_a_fact(self):
        r=with_locality();checked=action(JULY,purpose='Read initial schedule')
        first=result(calls=[scrape(),call_for(checked)],findings=[bathroom(r)],
                     followups=[checked,action()],done=False)
        with patch('screening.codex_research.run',side_effect=[first,TimeoutError('Interrupted')]):
            codex_research.research(r)
        self.assertEqual(r['evidence']['research']['status'],'partial_failure')
        self.assertEqual(r['evidence']['researched_facts']['property.bathrooms']['value'],2)
        def resume(system,packet,schema,**kwargs):
            self.assertEqual(packet['priority_follow_up']['target'],AUGUST)
            self.assertEqual(packet['follow_up_history'][0]['target'],JULY)
            return result(calls=[call_for(packet['priority_follow_up'])])
        with patch('screening.codex_research.run',side_effect=resume):codex_research.research(r)
        self.assertEqual(r['evidence']['research']['status'],'completed')
        self.assertTrue(all(t['status']=='checked' for t in r['evidence']['research']['follow_ups']))

    def test_changed_inputs_discard_unfinished_tasks_from_the_old_request(self):
        r=with_locality()
        with patch('screening.codex_research.run',side_effect=[result(followups=[action()]),TimeoutError('Interrupted')]):
            codex_research.research(r)
        r['inputs']['property']['address']='99 Different Road'
        with patch('screening.codex_research.run',return_value=result()) as run:codex_research.research(r)
        self.assertIsNone(run.call_args[0][1]['priority_follow_up'])

    def test_quota_envelopes_are_limited_even_without_object_data_or_text_content(self):
        envelopes=[{'structuredContent':{'success':False,'data':None,'error':'Quota exceeded'}},
                   {'structuredContent':{'success':False,'data':[],'error':'Daily limit reached'}},
                   {'isError':True,'structuredContent':{'error':'Quota exceeded'}},
                   {'isError':True,'structuredContent':{'error':'x'*700+' Quota exceeded'}},
                   {'content':[{'type':'text','text':json.dumps({'success':False,'data':None,'error':'Quota exceeded'})}]}]
        for envelope in envelopes:
            with self.subTest(envelope=envelope):
                r=with_locality();lead=action();call=call_for(lead);call['result']=envelope
                with patch('screening.codex_research.run',return_value=result(calls=[call],followups=[lead])):
                    codex_research.research(r)
                self.assertEqual(r['evidence']['research']['status'],'limited')
                self.assertEqual(r['evidence']['research']['follow_ups'][0]['status'],'unavailable')

    def test_a_later_attempt_retries_the_lookup_blocked_by_a_usage_limit(self):
        r=record()
        def blocked(system,packet,schema,**kwargs):
            return result(calls=[call_for(packet['priority_follow_up'],failed=True,text='Daily limit reached')],
                          followups=[action()])
        with patch('screening.codex_research.run',side_effect=blocked):codex_research.research(r)
        def resumed(system,packet,schema,**kwargs):
            tasks=packet['pending_follow_ups']
            self.assertEqual([t['id'] for t in tasks[:1]],['amenities'])
            self.assertIn(AUGUST,[t['target'] for t in tasks])
            return result(calls=[call_for(t) for t in tasks])
        with patch('screening.codex_research.run',side_effect=resumed):codex_research.research(r)
        self.assertEqual(r['evidence']['research']['status'],'completed')


if __name__=='__main__':unittest.main()
