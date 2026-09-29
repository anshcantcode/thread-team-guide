"""Local llama.cpp JSON completion transport for the unchanged evaluator client.

The installed server ignored response_format at /chat/completions in independent
controls. Its native /completion endpoint applies json_schema. Template rendering
does not run inference; each create() still makes exactly one model generation.
"""
import json
import time
from urllib.parse import urlparse
import httpx

JUDGE_SCHEMA={"type":"object","properties":{"correct":{"type":"boolean"},
    "explanation":{"type":"string"}},"required":["correct","explanation"],"additionalProperties":False}


class NativeJudgeTransport(httpx.BaseTransport):
    def __init__(self, endpoint, calls, *, transport=None, json_schema=None, record_callback=None):
        parsed=urlparse(endpoint)
        if parsed.scheme!="http" or parsed.hostname not in {"localhost","127.0.0.1","::1"}:
            raise ValueError("Judge transport requires loopback")
        self.client=httpx.Client(base_url=endpoint.removesuffix('/v1'),timeout=90,trust_env=False,transport=transport)
        self.calls=calls
        self.json_schema = JUDGE_SCHEMA if json_schema is None else json_schema
        self.record_callback = record_callback

    def checkpoint(self):
        if self.record_callback is not None:
            self.record_callback(self.calls)

    def handle_request(self, request):
        body=json.loads(request.content)
        record={"started_at":time.time(),"outcome":"pending","inference_requests":0,"template_requests":0,
                "inference_intents":0,"template_intents":0}
        self.calls.append(record)
        try:
            self.checkpoint()
            record['template_requests']=1
            record['template_intents']=1
            try:
                self.checkpoint()
            except BaseException:
                record['template_requests']=0  # Known failure before HTTP submission.
                raise
            rendered=self.client.post('/apply-template',json={"messages":body['messages'],
                "chat_template_kwargs":{"enable_thinking":False}})
            rendered.raise_for_status()
            payload={"prompt":rendered.json()['prompt'],
                "temperature":body['temperature'],"n_predict":body['max_tokens'],"cache_prompt":False,
                "json_schema":self.json_schema}
            record['inference_requests']=1
            record['inference_intents']=1
            try:
                self.checkpoint()
            except BaseException:
                record['inference_requests']=0  # Pending intent does not prove submission.
                raise
            result=self.client.post('/completion',json=payload)
            result.raise_for_status()
            value=result.json()
            record.update(outcome='success',native_response=value)
            if value.get('truncated') is True:
                raise ValueError('Judge exhausted its context; judgment rejected')
            prompt_tokens=value['tokens_evaluated']; completion_tokens=value['tokens_predicted']
            return httpx.Response(200,json={"id":"local-native-judge","object":"chat.completion",
                "created":int(time.time()),"model":value['model'],"choices":[{"index":0,
                "finish_reason":"length" if value.get('stop_type')=='limit' else 'stop',
                "message":{"role":"assistant","content":value['content']}}],
                "usage":{"prompt_tokens":prompt_tokens,"completion_tokens":completion_tokens,
                    "total_tokens":prompt_tokens+completion_tokens}})
        except BaseException as exc:
            record.update(outcome='error',error_type=type(exc).__name__)
            raise
        finally:
            record['finished_at']=time.time()
            self.checkpoint()

    def close(self):
        self.client.close()
