"""Protocol controls: unchanged prompt, one inference, actual result, visible failure."""
import json
from copy import deepcopy
import unittest
import httpx
from thread_agent.fdb3_judge_transport import NativeJudgeTransport


class JudgeTransportTests(unittest.TestCase):
    def test_exact_messages_render_once_and_one_fresh_generation_is_returned(self):
        paths=[]; evidence=[]
        messages=[{'role':'user','content':'independent control'}]
        def server(request):
            paths.append(request.url.path)
            body=json.loads(request.content)
            if request.url.path=='/apply-template':
                self.assertEqual(body['messages'],messages)
                return httpx.Response(200,json={'prompt':'server rendered prompt'})
            self.assertEqual(body['prompt'],'server rendered prompt')
            self.assertEqual(body['temperature'],0)
            self.assertEqual(body['n_predict'],200)
            self.assertIs(body['cache_prompt'],False)
            return httpx.Response(200,json={'content':'{"correct":false,"explanation":"fixture mismatch"}',
                'model':'fixture-local','tokens_evaluated':11,'tokens_predicted':7,'stop_type':'eos'})
        with httpx.Client(transport=NativeJudgeTransport('http://127.0.0.1:9/v1',evidence,
                transport=httpx.MockTransport(server))) as client:
            result=client.post('http://127.0.0.1:9/v1/chat/completions',json={
                'messages':messages,'temperature':0,'max_tokens':200}).json()
        self.assertEqual(paths,['/apply-template','/completion'])
        self.assertFalse(json.loads(result['choices'][0]['message']['content'])['correct'])
        self.assertEqual(result['usage']['total_tokens'],18)
        self.assertEqual(evidence[0]['inference_requests'],1)

    def test_template_error_cannot_invent_inference_or_success(self):
        evidence=[]
        with httpx.Client(transport=NativeJudgeTransport('http://127.0.0.1:9/v1',evidence,
                transport=httpx.MockTransport(lambda request:httpx.Response(500)))) as client:
            with self.assertRaises(httpx.HTTPStatusError):
                client.post('http://127.0.0.1:9/v1/chat/completions',json={'messages':[]})
        self.assertEqual(evidence[0]['inference_requests'],0)
        self.assertEqual(evidence[0]['outcome'],'error')

    def test_nonlocal_route_is_rejected(self):
        with self.assertRaises(ValueError):
            NativeJudgeTransport('https://external.example/v1',[])

    def test_truncated_judge_cannot_pass_even_when_json_is_complete(self):
        evidence=[]
        def server(request):
            if request.url.path=='/apply-template':
                return httpx.Response(200,json={'prompt':'independent control'})
            return httpx.Response(200,json={'content':'{"correct":true,"explanation":"looks valid"}',
                'model':'fixture-local','tokens_evaluated':4096,'tokens_predicted':11,
                'stop_type':'eos','truncated':True})
        with httpx.Client(transport=NativeJudgeTransport('http://127.0.0.1:9/v1',evidence,
                transport=httpx.MockTransport(server))) as client:
            with self.assertRaisesRegex(ValueError,'context'):
                client.post('http://127.0.0.1:9/v1/chat/completions',json={
                    'messages':[],'temperature':0,'max_tokens':200})
        self.assertEqual(evidence[0]['outcome'],'error')
        self.assertTrue(evidence[0]['native_response']['truncated'])
        self.assertEqual(evidence[0]['native_response']['tokens_predicted'],11)

    def test_failed_pre_http_checkpoint_counts_intent_without_unsent_request(self):
        for stage in ('template', 'inference'):
            with self.subTest(stage=stage):
                evidence=[]; paths=[]; snapshots=[]
                def server(request):
                    paths.append(request.url.path)
                    self.assertEqual(request.url.path, '/apply-template')
                    return httpx.Response(200, json={'prompt':'fixture'})
                def checkpoint(calls):
                    snapshots.append(deepcopy(calls[-1]))
                    if calls[-1]['outcome']=='pending' and calls[-1][stage+'_requests']==1:
                        raise OSError('authored checkpoint failure after recording intent')
                with httpx.Client(transport=NativeJudgeTransport('http://127.0.0.1:9/v1', evidence,
                        transport=httpx.MockTransport(server), record_callback=checkpoint)) as client:
                    with self.assertRaises(OSError):
                        client.post('http://127.0.0.1:9/v1/chat/completions', json={
                            'messages':[], 'temperature':0, 'max_tokens':200})
                self.assertEqual(paths, [] if stage=='template' else ['/apply-template'])
                self.assertEqual(evidence[0]['outcome'], 'error')
                self.assertEqual(evidence[0][stage+'_requests'], 0)
                self.assertEqual(evidence[0][stage+'_intents'], 1)
                self.assertEqual(snapshots[-1], evidence[0])
                self.assertTrue(any(row['outcome']=='pending' and row[stage+'_requests']==1 for row in snapshots))
