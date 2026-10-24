"""Execute the proposed documentation snippet over loopback HTTP fixtures."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import textwrap
import hashlib
import contextlib
from importlib.metadata import version
from http.server import ThreadingHTTPServer

root = Path(__file__).parent
fixture = root.parents[1]/'provenance/python-clients/check_clients.py'
spec = importlib.util.spec_from_file_location('fixture', fixture)
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
markers = {'en': '**Shared local inference for background workers:**',
           'ar': '**استدلال محلي مشترك للمهام الخلفية:**',
           'ko': '**백그라운드 작업을 위한 로컬 추론 공유:**',
           'pt-BR': '**Inferência local compartilhada para tarefas em segundo plano:**'}
snippets = []
for locale, marker in markers.items():
    text = (root/f'{locale}.md').read_text(encoding='utf-8')
    section = text[text.index(marker):]
    code = section.split('```python Code\n', 1)[1].split('```', 1)[0]
    snippets.append(textwrap.dedent(code))
assert len(set(snippets)) == 1, 'Localized executable snippets differ'
code = snippets[0]
socket.socket.connect = f.local_connect
server = ThreadingHTTPServer(('127.0.0.1', 0), f.Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
os.environ['ADAPTIVE_GATEWAY_ROOT'] = f'http://127.0.0.1:{server.server_port}/team/inference'
os.environ['ADAPTIVE_GATEWAY_KEY'] = 'fixture-key'
settings = {'model': f.MODEL, 'max_tokens':10923, 'reasoning_effort':'high',
            'temperature':0.73, 'extra_body':{'reasoning_budget_tokens':8192,
            'experimental_speed_projection':False,'pcie_frac':0.37}}
rows=[]
oldcwd=Path.cwd()
try:
    with contextlib.nullcontext(tempfile.mkdtemp(prefix='crewai-guide-', dir=None)) as tmp:
        os.chdir(tmp)
        Path('llm-settings.json').write_text(json.dumps(settings),encoding='utf-8')
        namespace={}
        exec(compile(code,'crewai-guide','exec'),namespace)
        for name, route in [('interactive_llm','/v1'),('background_llm','/background/v1')]:
            result=namespace[name].call([{'role':'user','content':'Fixture request, no model.'}])
            request=f.seen[-1]
            assert result=='fixture accepted'
            assert request['path']=='/team/inference'+route+'/chat/completions'
            assert request['authorization']=='Bearer fixture-key'
            for key in ('model','max_tokens','reasoning_effort','temperature'):
                assert request['body'][key]==settings[key]
            for key, value in settings['extra_body'].items():
                assert request['body'][key]==value
            rows.append({'name':name,'path':request['path'],'passed':True})
        assert len(f.seen)==2 and not f.blocked
finally:
    os.chdir(oldcwd)
    socket.socket.connect=f.original_connect
    server.shutdown(); server.server_close()
receipt={'passed':True,'scope':'actual CrewAI documentation construction and HTTP serialization against fixtures; no model or gateway run',
         'versions':{'crewai':version('crewai'),'openai':version('openai')},
         'snippet_sha256':hashlib.sha256(code.encode()).hexdigest(),
         'identical_locales':list(markers),'requests':rows,'external_connections':f.blocked}
(root/'result.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
print(json.dumps(receipt))
