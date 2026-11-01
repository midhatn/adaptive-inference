# SPDX-License-Identifier: Apache-2.0
"""Read-only terminal projections using the retained TaskStore/native-history checks."""
from dataclasses import asdict
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from bindings import read, sha


def checkpoint(path, task_id):
    # The same read-only SQL projection as the retained terminal auditor. Never
    # construct a TaskStore/authority in an audit: constructors can initialize.
    with closing(sqlite3.connect(Path(path).as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        row=db.execute('SELECT * FROM tasks WHERE task_id=?',(task_id,)).fetchone()
        if row is None:raise ValueError('Required retained checkpoint missing')
    return {**{k:row[k] for k in ('task_id','prompt','max_attempts','revision','owner_epoch')},
        'state':json.loads(row['state']),'metadata':json.loads(row['metadata']),
        'operation':None if row['inflight'] is None else json.loads(row['inflight']),
        'requires_reconciliation':bool(row['reconciliation'])}


def history(path, task_id):
    with closing(sqlite3.connect(Path(path).as_uri()+'?mode=ro',uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Task database integrity')
        return [list(row) for row in db.execute(
            'SELECT revision,event,payload FROM history WHERE task_id=? ORDER BY revision',(task_id,))]


def native_history(path, session_id):
    # Exact row projection used by the accepted Continue terminal auditor.
    with closing(sqlite3.connect(Path(path).as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        native_rows=[dict(x) for x in db.execute('SELECT * FROM messages ORDER BY id')]
        sessions=[dict(x) for x in db.execute('SELECT * FROM sessions')]
        if (db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or len(sessions)!=1
                or sessions[0]['id']!=session_id or sessions[0].get('parent_session_id')):
            raise ValueError('Native session database differs')
    decoded=[]
    for row in native_rows:
        if row['session_id']!=session_id or row['active']!=1 or row['compacted']!=0:
            raise ValueError('Native row scope differs')
        message={'role':row['role'],'content':row['content'],'_db_persisted':True,'_row_id':row['id'],
            'message_uid':row['message_uid'],'timestamp':row['timestamp']}
        for column,key in (('tool_call_uids','_tool_call_uids'),('tool_call_uid','_tool_call_uid'),('tool_calls','tool_calls')):
            if row[column]:message[key]=json.loads(row[column]) if column!='tool_call_uid' else row[column]
        for key in ('tool_call_id','tool_name','effect_disposition','finish_reason','reasoning'):
            if row[key]:message[key]=row[key]
        if row['role']=='assistant' and row['reasoning_content'] is not None:message['reasoning_content']=row['reasoning_content']
        decoded.append(message)
    return decoded


def verify_effect_rows(native, tools, effects):
    """Keep physical writes separate from exact native-durable logical retries."""
    from adaptive_inference.desktop.hermes import recovery as rec
    writes=[row for row in tools if row['name']=='write_file']
    if (any(type(row.get('reused')) is not bool for row in writes)
            or effects!=[row for row in writes if row['reused'] is False]):
        raise ValueError('Physical effects differ from durable non-reused tools')
    rec.verify_tool_rows(native,writes)
    originals={};ids=set()
    for row in writes:
        ident=row['tool_call_id'];operation=row['operation_id']
        if type(ident) is not str or not ident or ident in ids or type(operation) is not str or not operation:
            raise ValueError('Write receipt identity differs')
        ids.add(ident)
        calls=[call for message in native for call in message.get('tool_calls',[]) if call.get('id')==ident]
        if (len(calls)!=1 or calls[0]['function']['name']!=row['name']
                or json.loads(calls[0]['function']['arguments'])!=row['args']
                or row['fingerprint']!=rec.digest({'name':row['name'],'path':Path(row['args']['path']).name,
                    'args':{k:v for k,v in row['args'].items() if k!='path'}})):
            raise ValueError('Write receipt differs from its exact native intent')
        if row['reused'] is False:
            if operation in originals:raise ValueError('Duplicate physical write operation')
            originals[operation]=row
        else:
            original=originals.get(operation)
            if original is None or row!={**original,'tool_call_id':ident,'args':row['args'],'reused':True}:
                raise ValueError('Reused write differs from its preceding physical receipt')


def task_disk(run, task_id, pid, original, *, grant=None):
    """No SDK construction; independently reopen actual task/native/artifact files."""
    from adaptive_inference.desktop.hermes import recovery as rec
    run=Path(run);cp=checkpoint(run/'task.sqlite3',task_id);state=cp['state']
    spec=rec.task_contract(SimpleNamespace(**cp))
    if spec is None:raise ValueError('Explicit TaskSpec missing')
    native=native_history(run/'home/state.db',state['session_id'])
    rec.verify_tool_rows(native,state['tools'])
    rec.verify_validation_rows(native,state,cp['metadata'].get('pre_effect_validator'))
    rec.verify_artifacts(state,run/'work',task_spec=spec)
    completion=spec.completion(run/'work',state['tools'],state['output'])
    if len(spec.data['outputs'])!=1:raise ValueError('This case requires one declared output per task')
    artifact=spec.data['outputs'][0];path=run/'work'/artifact['name']
    diagnostics=run if grant is None else run/'executions'/grant['payload']['successor_id']
    if grant is not None and (task_id!=grant['payload']['successor_id'] or read(diagnostics/'grant.json')!=grant):
        raise ValueError('Exact selected result scope required')
    worker=read(diagnostics/f'result-{pid}.json')
    config=read(run/'home/config.yaml')
    if config['model']['context_length']!=65536 or config['compression']['threshold']!=.8:
        raise ValueError('Context configuration changed')
    effects=[json.loads(row) for row in (run/'effect-receipts.jsonl').read_text(encoding='utf-8').splitlines() if row.strip()]
    verify_effect_rows(native,state['tools'],effects)
    from adaptive_inference.control_mailbox import ACKS
    acknowledgements=state[ACKS]
    control=checkpoint(run/'task.sqlite3',acknowledgements['mailbox_task_id'])
    requests=control['state']['adaptive_inference.control_requests.v1']
    if len(requests)!=len(acknowledgements['receipts']) or any(
            {k:receipt[k] for k in ('sequence','request_id','command')}!=request
            for request,receipt in zip(requests,acknowledgements['receipts'])):
        raise ValueError('Control requests differ from actual owner acknowledgements')
    controls=[]
    for row in acknowledgements['receipts']:
        controls.append({**row,'owner_acknowledged':True})
    return {'run':str(run),'checkpoint':cp,'original':original,
        'history':history(run/'task.sqlite3',task_id),'plan':read(run/'plan.json'),
        'worker':worker,'worker_result_sha256':sha(diagnostics/f'result-{pid}.json'),
        'wire':read(run/'wire-observations.json'),'wire_sha256':sha(run/'wire-observations.json'),
        'effects':effects,'effects_sha256':sha(run/'effect-receipts.jsonl'),
        'artifact_name':artifact['name'],'artifact_sha256':sha(path),
        'artifact':read(path) if artifact['format']=='json' else path.read_text(encoding='utf-8'),
        'completion':completion,'native_history':native,'controls':controls,
        'input_sha256':{row['name']:sha(run/'work'/row['name']) for row in spec.data['inputs']}}


def preservation(row):
    return {key:row[key] for key in ('checkpoint','history','wire_sha256','effects_sha256',
                                    'artifact_sha256','input_sha256','worker_result_sha256')}
