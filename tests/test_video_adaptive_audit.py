"""Synthetic closed records and real read-only SQLite; no agent, model or UI."""
from contextlib import closing
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from adaptive_inference.control_mailbox import ACKS, REQUESTS
from adaptive_inference.desktop.hermes import recovery as rec
from adaptive_inference.task_store import TaskStore

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('video_adaptive_audit',
    ROOT/'examples/validation/video_coexistence/audit_adaptive.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
RESULTS = []
READ_CONNECTIONS = []


def save(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')


def utc(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


class ReadConnection(sqlite3.Connection):
    def close(self):
        super().close()
        self.record['closed'] = True


class AdaptiveAuditTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.run = self.root/'run'
        self.work = self.run/'hermes-task'
        (self.work/'home').mkdir(parents=True)
        (self.work/'work').mkdir()
        self.contract_path = ROOT/'examples/tasks/inventory/task.json'
        self.inputs = self.contract_path.parent/'inputs'
        self.contract = audit.TaskSpec.from_bytes(self.contract_path.read_bytes())
        raw_input = (self.inputs/'inventory.csv').read_bytes()
        (self.work/'work/inventory.csv').write_bytes(raw_input)
        content = json.dumps(audit.checks.inventory_oracle(raw_input))
        artifact = self.work/'work/replenishment.json'
        artifact.write_text(content, encoding='utf-8')
        args = {'path': 'replenishment.json', 'content': content}
        effect = {'name': 'write_file', 'tool_call_id': 'write-1', 'operation_id': 'operation-1',
            'args': args, 'result': '{"verified":true}', 'reused': False,
            'artifact_sha256': audit.sha(artifact),
            'fingerprint': rec.digest({'name': 'write_file', 'path': 'replenishment.json',
                                      'args': {'content': content}})}
        (self.work/'effect-receipts.jsonl').write_text(json.dumps(effect) + '\n', encoding='utf-8')
        # Only the existing evidence.native_history SQL projection is represented.
        columns = ['id', 'session_id', 'active', 'compacted', 'role', 'content', 'message_uid',
                   'timestamp', 'tool_call_uids', 'tool_call_uid', 'tool_calls', 'tool_call_id',
                   'tool_name', 'effect_disposition', 'finish_reason', 'reasoning', 'reasoning_content']
        native_rows = [
            {'role': 'assistant', 'tool_calls': json.dumps([{'id': 'write-1', 'type': 'function',
                'function': {'name': 'write_file', 'arguments': json.dumps(args)}}])},
            {'role': 'tool', 'content': effect['result'], 'tool_call_id': 'write-1'},
        ]
        with closing(sqlite3.connect(self.work/'home/state.db')) as db:
            db.execute('CREATE TABLE messages (' + ','.join(columns) + ')')
            db.execute('CREATE TABLE sessions (id, parent_session_id)')
            db.execute('INSERT INTO sessions VALUES (?,NULL)', ('session',))
            for index, row in enumerate(native_rows, 1):
                values = {'id': index, 'session_id': 'session', 'active': 1, 'compacted': 0,
                          'message_uid': 'message-' + str(index), 'timestamp': utc(105), **row}
                db.execute('INSERT INTO messages VALUES (' + ','.join('?' for _ in columns) + ')',
                           tuple(values.get(name) for name in columns))
            db.commit()
        native = audit.evidence.native_history(self.work/'home/state.db', 'session')
        controls = [{'sequence': i, 'request_id': command + '-1', 'command': command,
                     'outcome': 'applied', 'acknowledged_at_utc': utc(101 + i)}
                    for i, command in enumerate(('pause', 'resume'), 1)]
        state = rec.initial_state(self.contract.prompt, 'session')
        original_state = deepcopy(state)
        state.update(status='accepted', attempts=1, requests=1, admission_attempts=1,
            native_history=native, tools=[effect], output='done', deadline_clock=audit.qpc.CLOCK_ID,
            deadline_monotonic=910., **{ACKS: {'mailbox_task_id': 'mailbox', 'receipts': controls}})
        metadata = {**self.contract.metadata(), 'pre_effect_validator': self.contract.validator_identity()}
        store = TaskStore(self.work/'task.sqlite3')
        cp = store.create('task', self.contract.prompt, max_attempts=8, metadata=metadata, state=state)
        mailbox_state = rec.initial_state('controls', 'mailbox-session')
        mailbox_state[REQUESTS] = [{k: x[k] for k in ('sequence', 'request_id', 'command')} for x in controls]
        store.create('mailbox', 'controls', state=mailbox_state)
        original = {**asdict(cp), 'state': original_state}
        save(self.run/'original-checkpoint.private.json', original)
        config = self.work/'home/config.yaml'
        save(config, {'model': {'context_length': 65536}, 'compression': {'threshold': .8}})
        identity = {'version': 'synthetic-record-only', 'files': {}}
        save(self.run/'installed-package.private.json', identity)
        plan = {'model': audit.checks.MODEL, 'quality': audit.checks.QUALITY, 'max_requests': 8,
                'fixture': False, 'sdk_revision': audit.checks.SDK, 'package_identity': identity,
                'pins': {str(config): audit.sha(config)}}
        save(self.work/'plan.json', plan)
        self.worker = {'passed': True, 'completed': True, 'fixture': False, 'cleanup_errors': [],
            'context': audit.checks.CONTEXT, 'model': audit.checks.MODEL, 'quality': audit.checks.QUALITY,
            'sdk_revision': audit.checks.SDK, 'semantic_validation': 'oracle_matched', 'provider_calls': 1,
            'original_prompt_sha256': audit.checks.digest(self.contract.prompt),
            'artifacts': {'replenishment.json': audit.sha(artifact)}}
        save(self.work/'result-22.json', self.worker)
        save(self.work/'wire-observations.json', [{'model': audit.checks.MODEL,
            'quality': audit.checks.QUALITY, 'class': 'normal', 'gateway_request_id': 'request-1',
            'started_at': 104., 'finished_at': 105.}])
        gui = dict.fromkeys(('closed', 'child_exit_observed', 'pipe_threads_joined', 'pipe_handles_closed',
                             'process_handle_closed', 'verifier_handle_closed'), True)
        gui.update(child_exit_code=0, pending_pipe_operations=0, faults=[])
        listener = {'clean_close': True, 'resources_closed': True, 'faults': []}
        transport = dict.fromkeys(('pending_mutations', 'unknown_mutations', 'handlers',
                                  'pending_connections', 'stream_close_failures'), 0)
        transport.update(closed=True, stop_confirmed=True, faults=[])
        native_run = self.root/'native'; native_run.mkdir()
        native_identity = {'run': str(native_run), 'owner_id': 'owner', 'owner': {'pid': 44, 'created_filetime': 55, 'exe': 'synthetic'}}
        native_result = {**native_identity, 'state': 'stopped', 'stop_reason': 'requested', 'running': False, 'cleanup_confirmed': True,
            'server_exit_code': 0, 'processes': {'retained_total': 1, 'confirmed_exits': 1,
                                               'active': [], 'completed_tail': [{'exited': True}]}}
        save(native_run/'result.json', native_result)
        release = {'released': True, 'cleanup_confirmed': True, 'port_free': True, 'retained_processes': 1,
            'confirmed_process_exits': 1, 'retained_at_stop': [{'exited': True}],
            'identity': native_identity, 'owner_id': 'owner'}
        host = {'closed': True, 'normal_release_confirmed': True, 'owned_children_exited': True,
                'primary_error': None, 'controller_fault': None, 'cleanup_error': None, 'release': release}
        (self.run/'host').mkdir(); save(self.run/'host/result.json', host)
        self.result = {'schema': 'adaptive.desktop.windows-file-task.result.v1', 'clean_stop': True,
            'task_completed': True, 'asyncio_teardown_completed': True, 'retained_obligations_joined': True,
            'execution_expired': False, 'worker_outcome': 'task_completed', 'deadline_clock': audit.qpc.CLOCK_ID,
            'deadline_monotonic': 910., 'semantic_validation': 'oracle_matched',
            'artifacts': self.worker['artifacts'], 'task_spec_sha256': self.contract.sha256,
            'retained_worker_identity': {'pid': 22, 'creation_time_100ns': 234, 'containing_job_verified': True},
            'retained_gui_binding': {'host_epoch': 'host', 'session_id': 'view', 'task_id': 'task',
                                     'hwnd': 11, 'pid': 33, 'creation_time_100ns': 345},
            'all_retained_process_exits': [{'pid': 21, 'exit_code': 0}, {'pid': 22, 'exit_code': 0}],
            'lifecycle': {'worker_joined': True, 'host_closed': True, 'uncertain': False, 'fault': None},
            'gui_cleanup': gui, 'listener_cleanup': listener, 'transport_cleanup': transport, 'cleanup': host,
            'task_episodes': [{'task_id': 'task', 'gui_cleanup': gui, 'listener_cleanup': listener,
                               'transport_cleanup': transport}]}
        save(self.run/'result.private.json', self.result)
        self.events = [{'kind': 'worker_launched', 'pid': 21, 'label': 'prepare'},
                       {'kind': 'worker_launched', 'pid': 22, 'label': 'worker'},
                       *[{'kind': 'retained_process_exit', 'pid': pid, 'exit_code': 0, 'terminated': False} for pid in (21, 22)]]
        (self.run/'events.private.jsonl').write_text('\n'.join(map(json.dumps, self.events)))
        profile = self.root/'profile.json'; save(profile, {'synthetic': True})
        self.parent = {'run': str(self.run), 'exit_code': 0, 'retained_case_handle_exited': True,
            'normal_parent_exit': True, 'timed_out': False, 'emergency_termination_attempted': False,
            'supervision_errors': [], 'parent_source_unchanged': True, 'outer_deadline_s': 2700,
            'parent_source_sha256': audit.sha(audit.HERE/'run_adaptive.py'),
            'inputs': {'task_spec': str(self.contract_path), 'task_spec_sha256': self.contract.sha256,
                'task_spec_file_sha256': audit.sha(self.contract_path), 'task_budget': audit.BUDGET,
                'input_sha256': {'inventory.csv': audit.sha(self.inputs/'inventory.csv')},
                'task_inputs': str(self.inputs), 'profile': str(profile), 'profile_sha256': audit.sha(profile)}}
        save(Path(str(self.run) + '.supervisor.private.json'), self.parent)
        save(Path(str(self.run) + '.observer.private.json'), {'run': str(self.run), 'sources_unchanged': True,
            'source_sha256': {'observer': audit.sha(audit.HERE/'observe_adaptive.py')},
            'active_case_file_contents_read': False, 'end_reason': 'observation_deadline'})
        self.ui = {'run': str(self.run), 'deadline_clock': audit.qpc.CLOCK_ID,
            'window': self.result['retained_gui_binding'], 'actions': [
                {'method': 'resume', 'qpc_before': 10., 'qpc_after': 10.1, 'utc_before': utc(102.5),
                 'utc_after': utc(103.5), 'hwnd': 11, 'pid': 33},
                {'method': 'stop', 'qpc_before': 20., 'qpc_after': 20.1, 'utc_before': utc(110),
                 'utc_after': utc(111), 'hwnd': 11, 'pid': 33}]}
        self.ui_path = self.root/'ui.json'; save(self.ui_path, self.ui)

    def run_audit(self, name='audit.json'):
        original_connect = sqlite3.connect
        def connect(path, *args, **kwargs):
            db = original_connect(path, *args, factory=ReadConnection, **kwargs)
            db.record = {'uri': str(path), 'read_only': str(path).endswith('?mode=ro')
                         and kwargs.get('uri') is True, 'closed': False}
            READ_CONNECTIONS.append(db.record)
            return db
        with mock.patch.object(sqlite3, 'connect', side_effect=connect):
            result = audit.audit(self.run, self.ui_path, self.root/name,
                                 parent_joined=True, observer_joined=True)
        RESULTS.append({'test': self.id(), 'synthetic_fixture_only': True, 'result': result})
        self.assertTrue(all(x['read_only'] and x['closed'] for x in READ_CONNECTIONS))
        return result

    def test_terminal_projection_uses_read_only_sql_and_separate_scope(self):
        result = self.run_audit()
        self.assertTrue(result['passed'], result)
        self.assertEqual((result['physical_writes'], result['provider_calls']), (1, 1))
        self.assertEqual(result['user_controls']['resume_request_ids'], ['resume-1'])
        self.assertEqual(result['observer_end_reason'], 'observation_deadline')
        self.assertFalse(result['video_qualified'])
        self.assertFalse(result['m3_qualified'])

    def test_missing_action_bracket_stays_incomplete_without_gui_projection(self):
        del self.ui['actions'][0]['qpc_before']; save(self.ui_path, self.ui)
        result = self.run_audit()
        self.assertFalse(result['passed'])
        self.assertEqual(result['user_controls']['status'], 'incomplete')
        self.assertNotIn('resume_request_ids', result['user_controls'])
        self.assertTrue(result['checks']['owned_terminal_cleanup'])

    def test_extra_action_or_wrong_window_stays_incomplete(self):
        self.ui['actions'].append(deepcopy(self.ui['actions'][0])); save(self.ui_path, self.ui)
        self.assertEqual(self.run_audit()['user_controls']['status'], 'incomplete')
        self.ui['actions'].pop(); self.ui['actions'][0]['pid'] = 999; save(self.ui_path, self.ui)
        self.assertEqual(self.run_audit('wrong-window.json')['user_controls']['status'], 'incomplete')

    def test_duplicate_physical_write_and_changed_quality_are_rejected(self):
        effects = self.work/'effect-receipts.jsonl'; original = effects.read_bytes()
        effects.write_bytes(original + original)
        self.assertFalse(self.run_audit()['passed'])
        effects.write_bytes(original)
        self.worker['quality'] = {**self.worker['quality'], 'max_tokens': 10}
        save(self.work/'result-22.json', self.worker)
        result = self.run_audit('wrong-quality.json')
        self.assertFalse(result['passed'])
        self.assertIn('quality', result['error'])

    def test_join_attestations_and_normal_parent_are_required_before_sql(self):
        with mock.patch.object(audit.evidence, 'task_disk') as disk:
            with self.assertRaisesRegex(ValueError, 'join retained'):
                audit.audit(self.run, self.ui_path, self.root/'forbidden.json')
            disk.assert_not_called()
            self.parent['emergency_termination_attempted'] = True
            save(Path(str(self.run) + '.supervisor.private.json'), self.parent)
            result = self.run_audit()
            self.assertFalse(result['passed'])
            disk.assert_not_called()

    def test_missing_worker_wait_or_uncertain_cleanup_cannot_pass(self):
        with self.assertRaisesRegex(ValueError, 'wait evidence'):
            audit.worker_lifetime(self.result, self.events[:2])
        self.result['transport_cleanup']['unknown_mutations'] = 1
        with self.assertRaisesRegex(ValueError, 'cleanup incomplete'):
            audit.cleanup(self.result, self.result['cleanup'], 'task')


if __name__ == '__main__':
    unittest.main()
