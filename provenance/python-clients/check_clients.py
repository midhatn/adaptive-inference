"""Exercise installed client SDKs against a loopback fixture; never runs a model."""
import argparse
import asyncio
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version

os.environ['OTEL_SDK_DISABLED'] = 'true'
os.environ['CREWAI_TELEMETRY_DISABLED'] = 'true'
os.environ['ANONYMIZED_TELEMETRY'] = 'False'
os.environ['LANGCHAIN_TRACING_V2'] = 'false'
ROOT = Path(__file__).resolve().parents[2]
MODEL = 'qwen3.8-flash-next-iq3_s-adaptive-media-beta'
seen = []
blocked = []
original_connect = socket.socket.connect
def local_connect(sock, address):
    if isinstance(address, tuple) and address[0] not in {'127.0.0.1','::1','localhost'}:
        blocked.append(str(address))
        raise RuntimeError('External transport denied during SDK fixture test')
    return original_connect(sock, address)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        seen.append({'path':self.path, 'authorization':self.headers.get('Authorization'), 'body':body})
        response = {'id':'fixture-only', 'object':'chat.completion', 'created':1,
                    'model':body['model'], 'choices':[{'index':0,'message':{'role':'assistant','content':'fixture accepted'},'finish_reason':'stop'}],
                    'usage':{'prompt_tokens':10,'completion_tokens':2,'total_tokens':12}}
        if body.get('stream'):
            chunks = [dict(response, object='chat.completion.chunk', usage=None, choices=[{'index':0,'delta':{'role':'assistant','content':'fixture accepted'},'finish_reason':None}]),
                      dict(response, object='chat.completion.chunk', usage=None, choices=[{'index':0,'delta':{},'finish_reason':'stop'}]),
                      dict(response, object='chat.completion.chunk', choices=[])]
            raw=(''.join('data: '+json.dumps(c)+'\n\n' for c in chunks)+'data: [DONE]\n\n').encode()
        else:
            raw=json.dumps(response).encode()
        self.send_response(200)
        self.send_header('Content-Type','text/event-stream' if body.get('stream') else 'application/json')
        self.send_header('Content-Length',str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

def load(name):
    path=ROOT/'examples'/'agents'/f'{name}_client.py'
    spec=importlib.util.spec_from_file_location(name+'_recipe',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def main():
    parser=argparse.ArgumentParser(description='Installed SDK client conformance over HTTP fixtures; no model runs')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    seen.clear(); blocked.clear()
    socket.socket.connect = local_connect
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    base=f'http://127.0.0.1:{server.server_port}/team/inference/v1'
    os.environ['ADAPTIVE_CONFORMANCE_KEY']='fixture-key'
    options={'max_tokens':10923, 'temperature':0.73, 'reasoning_effort':'high',
             'extra_body':{'reasoning_budget_tokens':8192,'experimental_speed_projection':False,'pcie_frac':0.37}}
    rows=[]
    try:
        for name in ('langgraph','crewai','autogen'):
            for background, mode in ((False,'text'),(True,'text'),(False,'stream'),(True,'stream'),(True,'tools')):
                before=len(seen)
                row={'client':name,'background':background,'mode':mode}
                try:
                    generation_options = copy.deepcopy(options)
                    if mode=='stream' and name!='autogen': generation_options['streaming' if name=='langgraph' else 'stream'] = True
                    tool={'type':'function','function':{'name':'inspect_artifact','description':'Fixture, never executed','parameters':{'type':'object','properties':{'path':{'type':'string'}},'required':['path'],'additionalProperties':False},'strict':True}}
                    if mode=='tools' and name=='langgraph': generation_options['tools']=[tool]
                    kwargs={'background':background,'generation_options':generation_options,
                            'gateway_base_url':base,'api_key_env':'ADAPTIVE_CONFORMANCE_KEY'}
                    module=load(name)
                    if name=='langgraph':
                        graph=module.build_graph(MODEL,**kwargs)
                        output=graph.invoke({'messages':[('user','Fixture request, no real model.')]})['messages'][-1].content
                    elif name=='crewai':
                        llm=module.build_llm(MODEL,**kwargs)
                        output=llm.call([{'role':'user','content':'Fixture request, no real model.'}], **({'tools':[tool]} if mode=='tools' else {}))
                    else:
                        from autogen_core.models import UserMessage
                        info={'vision':False,'function_calling':True,'json_output':False,'family':'unknown','structured_output':False}
                        client=module.build_client(MODEL,info,**kwargs)
                        async def call():
                            try:
                                messages=[UserMessage(content='Fixture request, no real model.',source='user')]
                                if mode=='stream':
                                    parts=[]
                                    async for chunk in client.create_stream(messages):
                                        if isinstance(chunk,str): parts.append(chunk)
                                    return ''.join(parts)
                                extra={'tools':[tool['function']]} if mode=='tools' else {}
                                return (await client.create(messages,**extra)).content
                            finally: await client.close()
                        output=asyncio.run(call())
                    row['output']=output
                    row['requests']=seen[before:]
                    assert output=='fixture accepted' and len(seen)==before+1
                    captured=seen[-1]
                    suffix='/background/v1/chat/completions' if background else '/v1/chat/completions'
                    assert captured['path']=='/team/inference'+suffix
                    assert captured['authorization']=='Bearer fixture-key'
                    emitted=captured['body']
                    assert emitted['model']==MODEL
                    assert emitted.get('max_tokens',emitted.get('max_completion_tokens'))==10923
                    assert emitted['temperature']==0.73 and emitted['reasoning_effort']=='high'
                    assert all(emitted[k]==v for k,v in options['extra_body'].items())
                    assert emitted.get('stream',False)==(mode=='stream')
                    if mode=='tools':
                        assert emitted['tools'][0]['function']['name']==tool['function']['name']
                        assert emitted['tools'][0]['function']['parameters']==tool['function']['parameters']
                    row['passed']=True
                except Exception as exc:
                    row.update(passed=False,error=type(exc).__name__+': '+str(exc),requests=seen[before:])
                rows.append(row)
    finally:
        server.shutdown(); server.server_close(); thread.join(5)
        socket.socket.connect = original_connect
    result={'schema':'adaptive-inference.python-client-conformance.v1','passed':all(r['passed'] for r in rows) and not blocked,'versions':{p:version(p) for p in ('langgraph','langchain-openai','crewai','autogen-ext','openai')},'rows':rows,'external_connection_attempts':blocked,'models_run':False}
    result['known_client_normalizations']={'langchain':'max_tokens is emitted as max_completion_tokens with the same allowance; nonstandard response reasoning fields are not preserved','crewai':'SDK converts function schemas to strict mode; this suite supplies an already-strict schema and does not claim arbitrary input schemas remain identical'}
    result['scope']='Actual installed SDK clients over loopback HTTP fixtures; no gateway/native model/agent task/reboot qualification. Tools are serialized, not executed.'
    result['source_sha256']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),ROOT/'src/adaptive_inference/client_routing.py',*[ROOT/'examples/agents'/f'{n}_client.py' for n in ('langgraph','autogen','crewai')]]}
    if args.output:
        with args.output.open('x',encoding='utf-8') as f: f.write(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

    return 0 if result['passed'] else 1


if __name__ == "__main__":
    raise SystemExit(main())
