import hashlib, importlib.metadata, json, os, socket, sys, threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE=Path(__file__).resolve().parent
import runpy
runpy.run_path(str(HERE/'verify-sources.py'))['verify']()
SOURCE=HERE/'sources/aider'
sys.path.insert(0,str(SOURCE))
MODEL='qwen3.8-flash-next-iq3_s-adaptive-media-beta'
os.environ['LITELLM_LOCAL_MODEL_COST_MAP']='True'
os.environ['OPENAI_API_KEY']='fixture-key'
for key in ('OPENAI_BASE_URL','GITHUB_COPILOT_TOKEN'):
    os.environ.pop(key,None)
captures=[]
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        captures.append({'path':self.path,'body':body,'auth':self.headers.get('Authorization')})
        common={'id':'fixture','object':'chat.completion','created':0,'model':MODEL}
        if body.get('stream'):
            text=''
            for delta,finish in [({'role':'assistant','content':'fixture response'},None),({},'stop')]:
                text+='data: '+json.dumps(dict(common,object='chat.completion.chunk',choices=[{'index':0,'delta':delta,'finish_reason':finish}]))+'\n\n'
            payload=(text+'data: [DONE]\n\n').encode();mime='text/event-stream'
        else:
            payload=json.dumps(dict(common,choices=[{'index':0,'message':{'role':'assistant','content':'fixture response'},'finish_reason':'stop'}],usage={'prompt_tokens':1,'completion_tokens':1,'total_tokens':2})).encode();mime='application/json'
        self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)

server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
original_connect=socket.socket.connect
blocked=[]
def only_fixture(sock,address):
    # Windows asyncio's socketpair uses loopback while creating its self-pipe.
    # Permit loopback IPC; all model HTTP calls must still reach the fixture.
    if address[0] not in ('127.0.0.1','::1'):
        blocked.append(str(address));raise RuntimeError('Non-fixture socket refused')
    return original_connect(sock,address)
socket.socket.connect=only_fixture
try:
    from aider.models import Model, register_models, register_litellm_models
    config=HERE/'aider-model-settings.yml'
    config.write_text(f'''- name: openai/{MODEL}
  use_temperature: true
  extra_params:
    max_tokens: 10923
    num_retries: 0
    extra_body:
      reasoning_effort: high
      reasoning_budget_tokens: 8192
      experimental_speed_projection: false
''',encoding='utf-8')
    metadata=HERE/'aider-model-metadata.json'
    metadata.write_text(json.dumps({'openai/'+MODEL:{'max_input_tokens':65536,'max_output_tokens':10923,'input_cost_per_token':0,'output_cost_per_token':0,'litellm_provider':'openai'}}))
    assert register_models([str(config)])==[str(config)]
    assert register_litellm_models([str(metadata)])==[str(metadata)]
    model=Model('openai/'+MODEL,weak_model=False,editor_model=False)
    for route,stream in [('/v1',False),('/background/v1',True)]:
        os.environ['OPENAI_API_BASE']=f'http://127.0.0.1:{server.server_port}'+route
        tool={'name':'read_status','description':'Read fixture status','parameters':{'type':'object','properties':{'name':{'type':'string'}},'required':['name']}}
        _,response=model.send_completion([{'role':'user','content':'Fixture only.'}],[tool],stream,temperature=0.2)
        text=''.join(c.choices[0].delta.content or '' for c in response) if stream else response.choices[0].message.content
        assert text=='fixture response',text
        row=captures[-1];assert row['path']==route+'/chat/completions';assert row['auth']=='Bearer fixture-key'
        assert row['body']['tools']==[{'type':'function','function':tool}]
        for key,value in {'model':MODEL,'max_tokens':10923,'reasoning_effort':'high','reasoning_budget_tokens':8192,'experimental_speed_projection':False,'temperature':0.2}.items():assert row['body'][key]==value,(key,row['body'])
    assert len(captures)==2 and not blocked
    result={'schema':'adaptive-inference.aider-transport.v1','passed':True,'source_revision':'5dc9490bb35f9729ef2c95d00a19ccd30c26339c','client':'actual Aider Model/config registration and LiteLLM/OpenAI transport','scope':'loopback fixture HTTP; no agent task or model','versions':{n:importlib.metadata.version(n) for n in ('litellm','openai')},'requests':[{'path':r['path'],'body':r['body']} for r in captures],'external_socket_attempts':len(blocked),'source_sha256':{p:hashlib.sha256((SOURCE/p).read_bytes()).hexdigest() for p in ('aider/models.py','aider/llm.py')},'test_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (HERE/'aider-result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps({'passed':True,'requests':len(captures),'external_socket_attempts':len(blocked)}))
finally:
    socket.socket.connect=original_connect
    server.shutdown();server.server_close();thread.join(5)
