# SPDX-License-Identifier: Apache-2.0
"""Opt-in local OpenAI SDK provider invocation with proven non-dispatch deferral.

Public Hermes LLM middleware returns this genuine SDK response. This deliberately
does not call Hermes' single-use downstream closure or its private watchdog/relay.
No arbitrary HTTP error, timeout, lost proof, or changed gateway is retryable.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
import re
import time
import uuid


class Deferred(BaseException):
    def __init__(self, proof):
        self.proof = proof
        super().__init__('Gateway proved this exact attempt was not dispatched')


class AdmissionStop(BaseException):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def proof(response, request, *, instance, attempt):
    """Return a safe proof or None; malformed/partial/spoofed responses never retry."""
    expected = {'dispatched': False, 'gateway_instance': instance,
                'attempt_id': attempt, 'body_sha256': sha(request.content)}
    if response.status_code != 503 or len(response.content) > 16384:
        return None
    headers = {'X-Adaptive-Dispatch': 'not-dispatched', 'X-Adaptive-Gateway-Instance': instance,
               'X-Adaptive-Attempt-Id': attempt, 'X-Adaptive-Body-SHA256': expected['body_sha256']}
    if any(response.headers.get_list(k) != [v] for k,v in headers.items()):
        return None
    try:
        def unique(rows):
            result = {}
            for k,v in rows:
                if k in result: raise ValueError('duplicate key')
                result[k] = v
            return result
        body=json.loads(response.content, object_pairs_hook=unique,
                        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
        if (body.get('error',{}).get('type') != 'adaptive_inference_error'
                or body.get('error',{}).get('code') != 'admission_deferred'
                or type(body.get('admission')) is not dict
                or body['admission'].get('dispatched') is not False
                or body['admission'] != expected):
            return None
    except (ValueError, TypeError, AttributeError):
        return None
    return {'schema':'adaptive.not-dispatched.v1', 'http_status':503, **expected}


class Provider:
    def __init__(self, *, base_url, model, instance, boundary, deadline,
                 status=None, clock=time.monotonic, sleep=time.sleep):
        import httpx
        from openai import OpenAI
        if not re.fullmatch('[0-9a-f]{32}',instance):
            raise AdmissionStop('Explicit owned gateway instance required')
        self.base_url, self.model, self.instance = base_url, model, instance
        self.boundary, self.deadline, self.clock, self.sleep = boundary,deadline,clock,sleep
        self.current_attempt = self.body_sha256 = None
        self.client = OpenAI(base_url=base_url,api_key='local-no-key',max_retries=0,
            timeout=httpx.Timeout(180,connect=5),
            http_client=httpx.Client(trust_env=False,follow_redirects=False,
                                    timeout=httpx.Timeout(180,connect=5)))
        self.status_client=httpx.Client(trust_env=False,follow_redirects=False,timeout=5)
        self.status_reader=status or self.read_status

    def close(self):
        self.client.close();self.status_client.close()

    def read_status(self):
        response=self.status_client.get(self.base_url.removesuffix('/v1')+'/metrics')
        if response.status_code!=200 or len(response.content)>1024*1024:
            raise AdmissionStop('Gateway status unavailable')
        return response.json()

    def admitted(self):
        row=self.status_reader()
        if row.get('service')!='adaptive-inference' or row.get('instance')!=self.instance:
            raise AdmissionStop('Gateway identity changed or missing')
        state=row.get('scheduler',{}); resources=row.get('resources',{})
        if state.get('closing') is not False or state.get('backend_completion_uncertain') is not False:
            raise AdmissionStop('Gateway requires reconciliation')
        if (type(state.get('active')) is not bool or type(state.get('pending')) is not int
                or state['pending']<0 or type(resources.get('admission_allowed')) is not bool):
            raise AdmissionStop('Incomplete admission observation')
        return resources['admission_allowed'] and not state['active'] and state['pending']==0

    def execute(self, request, *, waiting, begin, deferred, completed, poll_control=None):
        original=copy.deepcopy(request)
        canonical=json.dumps(original,sort_keys=True,ensure_ascii=False)
        if len(canonical.encode())>512*1024 or original.get('model')!=self.model or original.get('stream',False) is not False:
            raise AdmissionStop('Provider request contract changed')
        # Preserve every supported caller option. Refuse reserved controls instead
        # of silently dropping them or letting them override host admission/auth.
        headers=copy.deepcopy(original.get('extra_headers') or {})
        if not isinstance(headers,dict) or any(k.lower() in {
                'x-adaptive-admission','x-adaptive-attempt-id','authorization'} for k in headers):
            raise AdmissionStop('Conflicting host-owned request headers')
        if 'timeout' in original:
            timeout=original['timeout']
            if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0 < timeout <= 1800:
                raise AdmissionStop('Caller timeout must be finite and within the pinned SDK ceiling')
        # The pinned Hermes builder supplies 1800s here. Preserve it unchanged;
        # its separate 180s private stale watchdog is deliberately not invoked.
        # This is an HTTP operation timeout, never a total wall-time promise.
        # The retained-process owner enforces the shared 900s whole-task bound.
        self.body_sha256=None
        while True:
            waiting(original)
            while True:
                if poll_control is not None: poll_control()
                if self.clock()>=self.deadline:
                    raise AdmissionStop('Admission wait deadline reached before dispatch')
                if self.admitted():break
                self.sleep(min(.25,max(0,self.deadline-self.clock())))
            if self.clock()>=self.deadline:
                raise AdmissionStop('Admission deadline reached before dispatch')
            self.current_attempt=uuid.uuid4().hex
            outgoing=copy.deepcopy(original)
            outgoing['extra_headers']={**headers,'X-Adaptive-Admission':'immediate',
                                      'X-Adaptive-Attempt-Id':self.current_attempt}
            if poll_control is not None: poll_control()
            operation=begin(self.current_attempt)
            try:
                response=self.client.chat.completions.create(**outgoing)
            except Deferred as signal:
                deferred(operation,signal.proof)
                self.sleep(min(.25,max(0,self.deadline-self.clock())))
                continue
            # Any other exception leaves the durable operation in flight. No
            # retry/fallback, including a lost or malformed no-dispatch proof.
            completed(operation)
            if json.dumps(original,sort_keys=True,ensure_ascii=False)!=canonical:
                raise AdmissionStop('Caller request mutated during provider invocation')
            return response

    def inspect_request(self, request):
        if request.method!='POST':return
        if self.clock()>=self.deadline:
            raise AdmissionStop('Admission deadline reached at final pre-send boundary')
        if (str(request.url)!=self.base_url+'/chat/completions'
                or request.headers.get('X-Adaptive-Admission')!='immediate'
                or request.headers.get('X-Adaptive-Attempt-Id')!=self.current_attempt):
            raise AdmissionStop('Provider transport escaped the bound attempt')
        body_sha=sha(request.content)
        if self.body_sha256 is None:self.body_sha256=body_sha
        elif self.body_sha256!=body_sha:
            raise AdmissionStop('Reissued request bytes changed')

    def inspect_response(self, request, response):
        response.read()
        evidence=proof(response,request,instance=self.instance,attempt=self.current_attempt)
        if evidence is not None:raise Deferred(evidence)
