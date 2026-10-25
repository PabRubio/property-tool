import copy
import tempfile
import time
import threading
import unittest
from unittest.mock import patch
from app import create_app
from screening.preflight import assess, correct, fingerprint
from screening.schema import validate_submission
from screening.providers import now
from screening.narrative import deterministic
from test_intake import brief


class PreflightTests(unittest.TestCase):
    def review(self,inputs,provider,status='needs_review'):
        return {'status':status,'fingerprint':fingerprint(inputs),'provider':provider,'summary':'Check the price against the other details.','issues':[]}

    def test_ai_decides_using_whole_brief_without_price_threshold(self):
        b=brief();b['property'].update(asking_price=15000000,floor_area_sqm=1200)
        b['investor']['notes']='Large estate with several buildings; price confirmed.'
        i=validate_submission(b)
        with patch.dict('os.environ',{'ANTHROPIC_API_KEY':'test'}),patch('screening.preflight.choose_model',return_value='test'),patch('screening.preflight.call_model',return_value={'summary':'The context explains the figures.','issues':[]}) as model:
            result=assess(i,'anthropic')
        self.assertEqual(result['status'],'clear')
        self.assertEqual(result['issues'],[])
        packet=model.call_args.args[4]
        self.assertEqual(packet['property']['asking_price'],15000000)
        self.assertEqual(packet['property']['floor_area_sqm'],1200)
        self.assertIn('several buildings',packet['investor']['notes'])
        self.assertNotIn('name',packet['investor']);self.assertNotIn('email',packet['investor'])
        self.assertNotIn('rule_flags',packet)
        self.assertNotIn('interest_rate_pct',packet['assumptions'])
        self.assertNotIn('insurance',packet['assumptions'])

    def test_issues_are_ai_findings_and_do_not_change_inputs(self):
        i=validate_submission(brief());before=copy.deepcopy(i)
        issue={'fields':['property.asking_price','property.floor_area_sqm'],'title':'Confirm consistency','explanation':'These inputs do not appear consistent in context.','severity':'review'}
        with patch.dict('os.environ',{'ANTHROPIC_API_KEY':'test'}),patch('screening.preflight.choose_model',return_value='test'),patch('screening.preflight.call_model',return_value={'summary':'A correction may be needed.','issues':[issue]}):
            result=assess(i,'anthropic')
        self.assertEqual(result['issues'],[issue]);self.assertEqual(result['status'],'needs_review')
        self.assertEqual(i,before)

    def test_explicit_additional_information_updates_fields(self):
        i=validate_submission(brief())
        output={'changes':[{'section':'property','key':'asking_price','value':1500000},{'section':'property','key':'bedrooms','value':6}], 'message':'Price corrected; six bedrooms retained.'}
        with patch.dict('os.environ',{'ANTHROPIC_API_KEY':'test'}),patch('screening.preflight.choose_model',return_value='test'),patch('screening.preflight.call_model',return_value=output):
            new,changes,message=correct(i,'The price should be £1.5m; six bedrooms is correct.','anthropic')
        self.assertEqual(new['property']['asking_price'],1500000)
        self.assertEqual(i['property']['asking_price'],250000)
        self.assertEqual(changes[0]['before'],250000)
        self.assertEqual(new['analyst_notes'],'The price should be £1.5m; six bedrooms is correct.')
        self.assertIn('corrected',message)

    def test_context_confirmation_changes_no_figures(self):
        i=validate_submission(brief())
        with patch.dict('os.environ',{'ANTHROPIC_API_KEY':'test'}),patch('screening.preflight.choose_model',return_value='test'),patch('screening.preflight.call_model',return_value={'changes':[],'message':'Context added.'}):
            new,changes,_=correct(i,'The agent confirmed the size includes the whole property.','anthropic')
        self.assertEqual(new['property'],i['property']);self.assertEqual(changes,[])
        self.assertNotEqual(fingerprint(new),fingerprint(i))

    def wait_for(self, app, record_id, finished_check=False):
        for _ in range(300):
            result=app.store.load(record_id)
            if (result['status']!='checking_inputs' if finished_check else result.get('job',{}).get('state') in ('done','failed')):
                return result
            time.sleep(.01)
        self.fail('Background operation did not finish')

    def evidence(self,*args,**kwargs):
        return {'retrieved_at':now(),'version':4,'sources':[],'comparables':[],'country_verified':True}

    def test_submission_checked_once_across_read_edit_generation_and_regeneration(self):
        with tempfile.TemporaryDirectory() as folder,patch('app.default_provider',return_value='none'),patch('screening.preflight.assess',side_effect=self.review) as review,patch('app.gather',side_effect=self.evidence),patch('screening.research.research'),patch('app.generate',side_effect=lambda r,p,**kw:deterministic(r)),patch('app.generate_report',return_value={'pdf':'test.pdf'}):
            app=create_app(folder);client=app.test_client();headers={'X-Local-Token':app.csrf_token}
            saved=client.post('/api/records',json={'inputs':brief()},headers=headers).get_json()
            review.assert_called_once();self.assertEqual(saved['status'],'draft')
            original_check=saved['preflight']
            for _ in range(3):client.get('/api/records/'+saved['id'])
            new=copy.deepcopy(saved['inputs']);new['property']['asking_price']=300000
            saved=client.put('/api/records/'+saved['id'],json={'revision':saved['revision'],'inputs':new},headers=headers).get_json()
            for _ in range(2):
                response=client.post('/api/records/'+saved['id']+'/pipeline',json={'revision':saved['revision'],'provider':'none'},headers=headers)
                self.assertEqual(response.status_code,202,response.get_json())
                saved=self.wait_for(app,saved['id'])
                self.assertEqual(saved['status'],'ready_for_review',saved.get('job'))
                self.assertEqual(saved['preflight'],original_check)
            review.assert_called_once()
            removed=client.post('/api/records/'+saved['id']+'/preflight',json={'revision':saved['revision']},headers=headers)
            self.assertEqual(removed.status_code,404)
            review.assert_called_once()

    def test_failed_check_is_saved_without_retry_or_generation_gate(self):
        with tempfile.TemporaryDirectory() as folder,patch('app.default_provider',return_value='none'),patch('screening.preflight.assess',wraps=assess) as review,patch('app.gather',side_effect=self.evidence),patch('screening.research.research'),patch('app.generate',side_effect=lambda r,p,**kw:deterministic(r)),patch('app.generate_report',return_value={'pdf':'test.pdf'}):
            app=create_app(folder);client=app.test_client();headers={'X-Local-Token':app.csrf_token}
            saved=client.post('/api/records',json={'inputs':brief()},headers=headers).get_json()
            self.assertEqual(saved['preflight']['status'],'failed')
            response=client.post('/api/records/'+saved['id']+'/pipeline',json={'revision':saved['revision'],'provider':'none'},headers=headers)
            self.assertEqual(response.status_code,202)
            updated=self.wait_for(app,saved['id'])
            self.assertEqual(updated['status'],'ready_for_review')
            self.assertEqual(updated['preflight'],saved['preflight']);review.assert_called_once()

    def test_restart_releases_check_without_retrying_it(self):
        with tempfile.TemporaryDirectory() as folder,patch('screening.preflight.assess') as review:
            app=create_app(folder);saved=app.store.create(validate_submission(brief()))
            saved.update(status='checking_inputs',preflight={'status':'running','fingerprint':fingerprint(saved['inputs']),'issues':[]})
            app.store.save(saved)
            restarted=create_app(folder);recovered=restarted.store.load(saved['id'])
            self.assertEqual(recovered['status'],'draft');self.assertEqual(recovered['preflight']['status'],'failed')
            self.assertEqual(recovered['inputs'],saved['inputs']);review.assert_not_called()

    def test_running_check_blocks_overlapping_writes_and_has_no_repeat_endpoint(self):
        started=threading.Event();release=threading.Event()
        def review(inputs,provider):
            started.set();release.wait(3);return self.review(inputs,provider)
        with tempfile.TemporaryDirectory() as folder,patch('app.default_provider',return_value='anthropic'),patch('screening.preflight.assess',side_effect=review) as check,patch('app.gather') as gather:
            app=create_app(folder);client=app.test_client();headers={'X-Local-Token':app.csrf_token}
            saved=client.post('/api/records',json={'inputs':brief()},headers=headers).get_json()
            try:
                self.assertTrue(started.wait(1));self.assertEqual(saved['status'],'checking_inputs')
                for endpoint in ('pipeline','gather','analyse'):
                    self.assertEqual(client.post('/api/records/'+saved['id']+'/'+endpoint,json={'revision':saved['revision']},headers=headers).status_code,400)
                self.assertEqual(client.put('/api/records/'+saved['id'],json={'revision':saved['revision'],'inputs':saved['inputs']},headers=headers).status_code,400)
                self.assertEqual(client.post('/api/records/'+saved['id']+'/preflight',json={},headers=headers).status_code,404)
                check.assert_called_once();gather.assert_not_called()
            finally:
                release.set();self.wait_for(app,saved['id'],finished_check=True)

    def test_additional_information_corrects_before_research_without_another_check(self):
        events=[]
        def correction(i,note,p):
            changed=copy.deepcopy(i);changed['property']['floor_area_sqm']=60;changed['analyst_notes']=note
            events.append('correction');return changed,[{'section':'property','key':'floor_area_sqm','before':None,'value':60}],'Area corrected to 60 m².'
        def gather(*args,**kwargs):events.append('paid-research');return self.evidence()
        with tempfile.TemporaryDirectory() as folder,patch('app.default_provider',return_value='none'),patch('screening.preflight.assess',side_effect=self.review) as check,patch('screening.preflight.correct',side_effect=correction) as corrector,patch('app.gather',side_effect=gather),patch('screening.research.research'),patch('app.generate',side_effect=lambda r,p,**kw:deterministic(r)),patch('app.generate_report',return_value={'pdf':'test.pdf'}):
            app=create_app(folder);client=app.test_client();headers={'X-Local-Token':app.csrf_token}
            saved=client.post('/api/records',json={'inputs':brief()},headers=headers).get_json()
            note='The area is 60 square metres.'
            response=client.post('/api/records/'+saved['id']+'/pipeline',json={'revision':saved['revision'],'provider':'none','analyst_notes':note},headers=headers)
            self.assertEqual(response.status_code,202)
            updated=self.wait_for(app,saved['id'])
            self.assertEqual(updated['status'],'ready_for_review',updated.get('job'))
            self.assertEqual(updated['inputs']['property']['floor_area_sqm'],60)
            self.assertEqual(updated['revision'],saved['revision']+1)
            self.assertEqual(updated['preflight'],saved['preflight'])
            self.assertEqual(updated['input_corrections']['changes'][0]['before'],None)
            self.assertTrue((app.store.folder(saved['id'])/'history'/'revision-1.json').exists())
            self.assertLess(events.index('correction'),events.index('paid-research'))
            check.assert_called_once();corrector.assert_called_once()
            client.post('/api/records/'+saved['id']+'/pipeline',json={'revision':updated['revision'],'provider':'none','analyst_notes':note},headers=headers)
            self.wait_for(app,saved['id']);check.assert_called_once();corrector.assert_called_once()

    def test_legacy_record_generation_does_not_start_a_late_check(self):
        with tempfile.TemporaryDirectory() as folder,patch('screening.preflight.assess') as check,patch('app.gather',side_effect=self.evidence),patch('screening.research.research'),patch('app.generate',side_effect=lambda r,p,**kw:deterministic(r)),patch('app.generate_report',return_value={'pdf':'test.pdf'}):
            app=create_app(folder);saved=app.store.create(validate_submission(brief()))
            client=app.test_client();headers={'X-Local-Token':app.csrf_token}
            client.post('/api/records/'+saved['id']+'/pipeline',json={'revision':saved['revision'],'provider':'none'},headers=headers)
            updated=self.wait_for(app,saved['id'])
            self.assertEqual(updated['status'],'ready_for_review');check.assert_not_called()

if __name__=='__main__':unittest.main()
