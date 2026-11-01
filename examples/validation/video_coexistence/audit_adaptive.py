# SPDX-License-Identifier: Apache-2.0
"""Terminal-only single-inventory projection; not video or whole-M3 acceptance."""
import argparse
from contextlib import closing
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys

from adaptive_inference.task_spec import BUDGET, TaskSpec

HERE = Path(__file__).resolve().parent
REUSED = HERE.parent / 'task_handover'


def _module(name, file):
    spec = importlib.util.spec_from_file_location(name, REUSED / file)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


# evidence.py's existing absolute binding import is scoped to its own source.
# Do not replace an unrelated example's cached module in a shared test process.
bindings = _module('video_terminal_bindings', 'bindings.py')
checks = _module('video_terminal_checks', 'checks.py')
qpc = _module('video_terminal_qpc', 'qpc.py')
_previous = sys.modules.get('bindings')
try:
    sys.modules['bindings'] = bindings
    evidence = _module('video_terminal_evidence', 'evidence.py')
finally:
    if _previous is None:
        sys.modules.pop('bindings', None)
    else:
        sys.modules['bindings'] = _previous
read, sha = bindings.read, bindings.sha


def require(value, message):
    if not value:
        raise ValueError(message)


def wall(value):
    result = datetime.fromisoformat(value)
    require(result.tzinfo is not None, 'Timezone-aware observed action required')
    return result.timestamp()


def observed_controls(ui, run, result, task):
    """Bind operator observations to durable ACKs, never invent GUI memory."""
    try:
        require(ui['run'] == str(run) and ui['deadline_clock'] == qpc.CLOCK_ID,
                'Observed run/clock differs')
        window = ui['window']
        require(window == result['retained_gui_binding']
                and window['task_id'] == task['checkpoint']['task_id'], 'Observed window differs')
        require(all(type(window[k]) is int and window[k] > 0
                    for k in ('hwnd', 'pid', 'creation_time_100ns')), 'Exact observed window identity required')
        actions = ui['actions']
        require([x['method'] for x in actions] == ['resume', 'stop'],
                'Exactly one observed Resume then one Stop required')
        times = []
        for action in actions:
            require(action['hwnd'] == window['hwnd'] and action['pid'] == window['pid'],
                    'Action observed on another window')
            require(qpc.qpc_bracket({**action, 'deadline_clock': ui['deadline_clock']},
                                   'qpc_before', 'qpc_after'), 'Missing/invalid action QPC bracket')
            before, after = wall(action['utc_before']), wall(action['utc_after'])
            require(before <= after, 'Invalid action UTC bracket')
            times.append((before, after))
        require(actions[0]['qpc_after'] < actions[1]['qpc_before'] and times[0][1] < times[1][0],
                'Observed actions overlap or reverse')
        controls = task['controls']
        require([x['command'] for x in controls] == ['pause', 'resume']
                and all(x['owner_acknowledged'] is True and x['outcome'] == 'applied' for x in controls),
                'Extra or unacknowledged durable controls')
        ack = wall(controls[1]['acknowledged_at_utc'])
        require(times[0][0] <= ack <= task['wire'][0]['started_at']
                and task['wire'][-1]['finished_at'] <= times[1][0],
                'Observed action does not bracket durable acknowledgement/task work')
        return {'status': 'verified', 'resume_request_ids': [controls[1]['request_id']],
                'basis': 'Operator-observed window/actions bound to sole durable Resume ACK; not transport._records or internal GUI evidence. Stop is an observed action plus retained stop-confirmed cleanup, not a fabricated mailbox request.'}
    except (KeyError, IndexError, TypeError, ValueError) as error:
        return {'status': 'incomplete', 'reason': str(error)}


def worker_lifetime(result, events):
    identity = result['retained_worker_identity']
    require(identity['containing_job_verified'] is True
            and type(identity['creation_time_100ns']) is int and identity['creation_time_100ns'] > 0,
            'Retained worker identity missing')
    launches = [x for x in events if x['kind'] == 'worker_launched']
    require([x['label'] for x in launches] == ['prepare', 'worker']
            and launches[1]['pid'] == identity['pid'], 'Single ordinary worker launch required')
    exits = result['all_retained_process_exits']
    require(exits == [{'pid': x['pid'], 'exit_code': 0} for x in launches],
            'Actual retained child exits differ')
    for child in launches:
        observed = [x for x in events if x['kind'] == 'retained_process_exit' and x['pid'] == child['pid']]
        require(observed and all(x['exit_code'] == 0 and x['terminated'] is False for x in observed),
                'Actual retained process wait evidence missing')
    return {**identity, 'exit_code': 0, 'joined': True}


def cleanup(result, host, task_id):
    require(result['schema'] == 'adaptive.desktop.windows-file-task.result.v1'
            and all(result.get(k) is True for k in ('clean_stop', 'task_completed',
                'asyncio_teardown_completed', 'retained_obligations_joined'))
            and result.get('execution_expired') is False and result.get('worker_outcome') == 'task_completed'
            and not any(result.get(k) for k in ('primary_error', 'cleanup_error', 'joined_obligation_errors')),
            'Ordinary completed task/cleanup required')
    require(result['lifecycle'] == {'worker_joined': True, 'host_closed': True, 'uncertain': False, 'fault': None},
            'Cooperative lifecycle differs')
    require(len(result['task_episodes']) == 1 and result['task_episodes'][0]['task_id'] == task_id
            and result.get('task_selection_revision', 0) == 0, 'One task episode required')
    gui, listener, transport = (result[k + '_cleanup'] for k in ('gui', 'listener', 'transport'))
    require(all(gui[k] is True for k in ('closed', 'child_exit_observed', 'pipe_threads_joined',
                'pipe_handles_closed', 'process_handle_closed', 'verifier_handle_closed'))
            and gui['child_exit_code'] == 0 and gui['pending_pipe_operations'] == 0 and not gui['faults'],
            'GUI cleanup incomplete')
    require(listener['clean_close'] is True and listener['resources_closed'] is True and not listener['faults']
            and transport['closed'] is True and transport['stop_confirmed'] is True and not transport['faults']
            and all(transport[k] == 0 for k in ('pending_mutations', 'unknown_mutations', 'handlers',
                                               'pending_connections', 'stream_close_failures')),
            'Listener/transport cleanup incomplete')
    require(all(result['task_episodes'][0][k] == result[k] for k in
                ('gui_cleanup', 'listener_cleanup', 'transport_cleanup')), 'Episode cleanup differs')
    require(host == result['cleanup'] and all(host[k] is True for k in
                ('closed', 'normal_release_confirmed', 'owned_children_exited'))
            and all(host[k] is None for k in ('primary_error', 'controller_fault', 'cleanup_error')),
            'Actual native host cleanup differs')
    release = host['release']
    require(all(release[k] is True for k in ('released', 'cleanup_confirmed', 'port_free'))
            and release['confirmed_process_exits'] == release['retained_processes'] > 0
            and all(x['exited'] is True for x in release['retained_at_stop']),
            'Retained native release incomplete')


def audit(run, ui_observation, output, *, parent_joined=False, observer_joined=False):
    if parent_joined is not True or observer_joined is not True:
        raise ValueError('Operator must join retained parent and observer before terminal reads')
    run, output = Path(run).resolve(strict=True), Path(output)
    require(output.is_absolute() and not output.exists() and output.parent.is_dir()
            and not output.resolve().is_relative_to(run), 'Fresh audit file outside the run required')
    receipt = {'schema': 'adaptive.single-inventory-terminal-audit.v1', 'passed': False, 'checks': {},
        'operator_handle_attestations': {'parent_joined': True, 'observer_joined': True,
            'scope': 'Caller-owned handle attestations permit terminal reads; not independent OS join proof.'},
        'user_controls': {'status': 'incomplete'}, 'video_qualified': False, 'm3_qualified': False,
        'scope': 'One ordinary inventory task, observation-bound Resume/Stop and retained terminal cleanup only.'}
    pins = {}
    def track(path):
        path = Path(path).resolve(strict=True)
        pin = sha(path)
        require(str(path) not in pins or pins[str(path)] == pin, 'Terminal input changed')
        pins[str(path)] = pin
        return path
    def data(path):
        return read(track(path))
    def check(name, condition):
        receipt['checks'][name] = bool(condition)
        require(condition, name)
    try:
        for file in (__file__, REUSED/'bindings.py', REUSED/'evidence.py', REUSED/'checks.py', REUSED/'qpc.py'):
            track(file)
        parent = data(Path(str(run) + '.supervisor.private.json'))
        check('normal_retained_parent', parent['run'] == str(run) and parent['exit_code'] == 0
            and parent['retained_case_handle_exited'] is True and parent['normal_parent_exit'] is True
            and parent['timed_out'] is False and parent['emergency_termination_attempted'] is False
            and parent['supervision_errors'] == [] and parent['parent_source_unchanged'] is True
            and parent['parent_source_sha256'] == sha(track(HERE/'run_adaptive.py'))
            and parent['outer_deadline_s'] == 2700)
        observer = data(Path(str(run) + '.observer.private.json'))
        check('retained_observer_record', observer['run'] == str(run) and observer['sources_unchanged'] is True
            and observer['source_sha256']['observer'] == sha(track(HERE/'observe_adaptive.py'))
            and observer['active_case_file_contents_read'] is False)
        receipt['observer_end_reason'] = observer['end_reason']
        # Parent and observer attestations/receipts have been consumed before SQL.
        result = data(run/'result.private.json')
        original = data(run/'original-checkpoint.private.json')
        events = [json.loads(x) for x in track(run/'events.private.jsonl').read_text().splitlines() if x.strip()]
        life = worker_lifetime(result, events)
        check('retained_worker_wait', True)
        work = run/'hermes-task'
        for file in ('task.sqlite3', 'home/state.db', 'home/config.yaml', 'plan.json',
                     'wire-observations.json', 'effect-receipts.jsonl', f"result-{life['pid']}.json"):
            track(work/file)
        task = evidence.task_disk(work, original['task_id'], life['pid'], original)
        task['lifetime'] = life
        contract = TaskSpec.from_metadata(task['checkpoint']['metadata'])
        bound = parent['inputs']
        supplied = TaskSpec.from_bytes(track(bound['task_spec']).read_bytes())
        expected = TaskSpec.from_bytes(track(HERE.parents[1]/'tasks/inventory/task.json').read_bytes())
        check('unchanged_inventory_contract', contract == supplied == expected and contract.data['budget'] == BUDGET
            and bound['task_budget'] == BUDGET and bound['task_spec_sha256'] == contract.sha256
            and sha(track(bound['task_spec'])) == bound['task_spec_file_sha256']
            and task['artifact_name'] == 'replenishment.json'
            and task['input_sha256'] == bound['input_sha256'])
        for name, pin in task['input_sha256'].items():
            check('input_' + name, sha(track(work/'work'/name)) == pin
                  == sha(track(Path(bound['task_inputs'])/name)))
        track(work/'work'/task['artifact_name'])
        check('independent_inventory_oracle', task['artifact'] == checks.inventory_oracle(
            (work/'work/inventory.csv').read_bytes()))
        check('installed_identity', task['plan']['package_identity'] == data(run/'installed-package.private.json'))
        for path, pin in task['plan']['pins'].items():
            check('pin_' + Path(path).name, sha(track(path)) == pin)
        check('profile_unchanged', sha(track(bound['profile'])) == bound['profile_sha256'])
        check('same_task_deadline', result['deadline_clock'] == qpc.CLOCK_ID
            and task['checkpoint']['state']['deadline_clock'] == qpc.CLOCK_ID
            and result['deadline_monotonic'] == task['checkpoint']['state']['deadline_monotonic'])
        # mode=ro, explicitly closed: no TaskStore constructor or mutable authority.
        with closing(sqlite3.connect((work/'task.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
            actual = list(db.execute('SELECT task_id,owner_epoch,inflight,reconciliation FROM tasks'))
        mailbox_id = task['checkpoint']['state']['adaptive_inference.control_acks.v1']['mailbox_task_id']
        check('only_released_task_and_mailbox', {x[0] for x in actual} == {original['task_id'], mailbox_id}
            and all(x[1] is None and x[2] is None and not x[3] for x in actual))
        try:
            ui = data(ui_observation)
            receipt['user_controls'] = observed_controls(ui, run, result, task)
        except (OSError, ValueError) as error:
            receipt['user_controls'] = {'status': 'incomplete', 'reason': str(error)}
        if receipt['user_controls']['status'] == 'verified':
            task['gui_resume_ids'] = receipt['user_controls']['resume_request_ids']
            checks.check_task(task, semantic='oracle_matched', grant=None)
            check('single_task_contract', True)
        else:
            receipt['checks']['single_task_contract'] = False
        check('ordinary_semantic_result', result['semantic_validation'] == 'oracle_matched'
            and result['artifacts'] == task['worker']['artifacts']
            and result['task_spec_sha256'] == contract.sha256)
        host = data(run/'host/result.json')
        cleanup(result, host, original['task_id'])
        check('owned_terminal_cleanup', True)
        release = host['release']
        native = data(Path(release['identity']['run'])/'result.json')
        count = native['processes']['retained_total']
        check('actual_last_native_owner', native['owner_id'] == release['owner_id']
            and native['run'] == release['identity']['run'] and native['owner'] == release['identity']['owner']
            and native['state'] == 'stopped' and native['running'] is False
            and native['stop_reason'] == 'requested' and not native.get('error')
            and not (native.get('memory') or {}).get('error')
            and native['cleanup_confirmed'] is True and native['server_exit_code'] == 0
            and native['processes']['active'] == [] and native['processes']['confirmed_exits'] == count
            and type(count) is int and count == release['retained_processes']
            and all(x['exited'] for x in native['processes']['completed_tail']))
        check('all_inputs_unchanged', all(sha(path) == pin for path, pin in pins.items()))
        receipt.update(passed=all(receipt['checks'].values()), provider_calls=len(task['wire']),
            physical_writes=len(task['effects']), execution_budget_s=900, outer_deadline_s=2700,
            worker_lifetime=life, control_projection='observation_bound',
            native_scope='Final native owner plus ordinary host cleanup receipt; not intermediate release timing or OS-wide process proof.')
    except Exception as error:
        receipt['error'] = type(error).__name__ + ': ' + str(error)
    finally:
        receipt['input_sha256'] = pins
        bindings.save(output, receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('run', 'ui-observation', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--parent-joined', action='store_true')
    parser.add_argument('--observer-joined', action='store_true')
    args = parser.parse_args(argv)
    result = audit(args.run, args.ui_observation, args.output,
                   parent_joined=args.parent_joined, observer_joined=args.observer_joined)
    print(json.dumps(result, allow_nan=False))
    return 0 if result['passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
