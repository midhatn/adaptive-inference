"""Declared file aliases through real filesystem and SQLite recovery; no SDK/model."""
from copy import deepcopy
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from adaptive_inference.task_spec import TaskSpec, digest
from adaptive_inference.task_store import ReconciliationRequired
from adaptive_inference.desktop.hermes import recovery as rec
from task_spec_support import spec_data
import test_task_spec_recovery as baseline


def absolute_alias(work, name):
    value = str(work.resolve() / name)
    # Mirrors the actual native Windows argument: repeated separators, not
    # JSON-escape normalization. The raw string must reach the effect unchanged.
    return value.replace('\\', '\\\\') if os.name == 'nt' else value


class FileAliasTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.work = self.root / 'work'; self.work.mkdir()
        self.other = self.root / 'other'; self.other.mkdir()
        for directory in (self.work, self.other):
            (directory / 'notes.txt').write_bytes(b'First note.\nSecond note.\n')
        self.spec = TaskSpec(spec_data())

    def test_declared_relative_absolute_and_repeated_separator_spellings(self):
        for name, write in (('notes.txt', False), ('answer.txt', True)):
            aliases = [name, './' + name, str(self.work / name), absolute_alias(self.work, name)]
            if os.name == 'nt':
                aliases += ['.\\' + name, str(self.work / name).replace('\\', '/')]
            for alias in aliases:
                with self.subTest(alias=alias, write=write):
                    self.assertEqual(self.spec.file_path(self.work, alias, write=write), self.work / name)

    def test_outside_traversal_special_paths_and_filename_changes_refused(self):
        invalid = [str(self.other / 'notes.txt'), '../work/notes.txt', './other/notes.txt',
            str(self.work / '..' / 'work' / 'notes.txt'), 'notes.txt/', 'answer.txt\\', 'NOTES.TXT',
            'undeclared.txt', 'C:notes.txt', '\\notes.txt', '\\\\host\\share\\notes.txt',
            '\\\\?\\C:\\notes.txt', '\\\\.\\C:\\notes.txt', 'notes.txt:stream',
            str(self.work / 'notes.txt') + ':stream', '', 'notes.txt\x00', None]
        for alias in invalid:
            with self.subTest(alias=alias), self.assertRaises((ValueError, OSError)):
                self.spec.file_path(self.work, alias)
        with self.assertRaises(ValueError):
            self.spec.file_path(self.work, absolute_alias(self.work, 'notes.txt'), write=True)

    def test_work_bound_validator_accepts_alias_without_changing_arguments(self):
        args = {'path': absolute_alias(self.work, 'answer.txt'), 'content': 'A summary.'}
        before = deepcopy(args)
        self.assertFalse(self.spec.validate_write('write_file', args).accepted)
        self.assertTrue(self.spec.validate_write('write_file', args, work=self.work).accepted)
        self.assertEqual(args, before)
        self.assertFalse(self.spec.validate_write('write_file',
            {'path': str(self.other / 'answer.txt'), 'content': 'wrong task'}, work=self.work).accepted)

    def test_hardlinked_declared_input_and_output_refused(self):
        os.link(self.work / 'notes.txt', self.other / 'input-link.txt')
        with self.assertRaises(ValueError): self.spec.file_path(self.work, 'notes.txt')
        (self.other / 'answer.txt').write_text('outside', encoding='utf-8')
        os.link(self.other / 'answer.txt', self.work / 'answer.txt')
        with self.assertRaises(ValueError): self.spec.file_path(self.work, './answer.txt', write=True)

    def test_symlink_file_and_workspace_refused(self):
        target = self.other / 'answer.txt'; target.write_text('outside', encoding='utf-8')
        try:
            (self.work / 'answer.txt').symlink_to(target)
            (self.root / 'work-link').symlink_to(self.work, target_is_directory=True)
        except OSError as exc:
            self.skipTest('Actual symlink creation unavailable: ' + str(exc.winerror if os.name == 'nt' else exc.errno))
        with self.assertRaises(ValueError): self.spec.file_path(self.work, 'answer.txt', write=True)
        with self.assertRaises(ValueError): self.spec.file_path(self.root / 'work-link', 'notes.txt')

    def test_reparse_workspace_refused_before_resolution(self):
        info = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        with patch.object(Path, 'lstat', return_value=info), self.assertRaises(ValueError):
            self.spec.file_path(self.work, 'notes.txt')

    def test_completion_audits_all_write_aliases_instead_of_ignoring_invalid_receipt(self):
        raw = b'A summary.'; (self.work / 'answer.txt').write_bytes(raw)
        receipt = {'name': 'write_file', 'args': {'path': absolute_alias(self.work, 'answer.txt')},
            'artifact_sha256': digest(raw)}
        self.assertEqual(self.spec.completion(self.work, [receipt], 'done')['artifacts'],
            {'answer.txt': digest(raw)})
        invalid = deepcopy(receipt); invalid['args']['path'] = str(self.other / 'answer.txt')
        with self.assertRaises(ValueError): self.spec.completion(self.work, [receipt, invalid], 'done')


class RecoveryAliasTests(unittest.TestCase):
    # Reuse the established real-SQLite fixture without inheriting and duplicating
    # its baseline tests. Native intent is committed before every adapter call.
    setUp = baseline.TaskRecoveryTests.setUp
    prepare = baseline.TaskRecoveryTests.prepare
    claim = baseline.TaskRecoveryTests.claim
    release = baseline.TaskRecoveryTests.release
    call = baseline.TaskRecoveryTests.call

    def finish(self):
        self.db.append({'role': 'assistant', 'content': 'Created the declared output.'})
        self.controller.finish({'completed': True, 'failed': False, 'interrupted': False,
            'final_response': 'Created the declared output.'})
        self.assertEqual(self.owned.checkpoint.state['status'], 'accepted')

    def test_absolute_read_write_flush_reclaim_alias_dedupe_and_completion(self):
        self.prepare()
        read = {'path': absolute_alias(self.work, 'notes.txt')}
        self.call('read_file', read)
        original = {'path': absolute_alias(self.work, 'answer.txt'), 'content': 'Two short notes.'}
        first = self.call('write_file', original)
        self.assertEqual(self.effects, [('read_file', read), ('write_file', original)])
        physical_bytes = (self.run / 'effect-receipts.jsonl').read_bytes()
        original_receipt = deepcopy(self.owned.checkpoint.state['tools'][-1])
        self.release(); self.claim()
        self.assertTrue(rec.resumable(self.owned, self.db, self.work))
        retry = {'path': './answer.txt', 'content': original['content']}
        self.assertEqual(self.call('write_file', retry), first)
        current = self.owned.checkpoint.state['tools'][-1]
        self.assertEqual(current['args'], retry)
        self.assertNotEqual(current['tool_call_id'], original_receipt['tool_call_id'])
        self.assertTrue(current['reused'])
        for key in ('fingerprint', 'operation_id', 'artifact_sha256', 'result'):
            self.assertEqual(current[key], original_receipt[key])
        self.assertEqual((self.run / 'effect-receipts.jsonl').read_bytes(), physical_bytes)
        self.assertEqual(json.loads(physical_bytes)['args'], original)
        calls = [call for row in rec.native_history(self.db, 'session') for call in row.get('tool_calls', [])]
        self.assertEqual(json.loads(calls[-1]['function']['arguments']), retry)
        self.assertEqual(len(self.effects), 2)
        self.release(); self.claim()
        self.assertTrue(rec.resumable(self.owned, self.db, self.work))
        self.finish()
        self.assertEqual(self.owned.checkpoint.prompt, self.spec.prompt)

    def test_absolute_rejected_proposal_reclaims_and_corrects_through_relative_alias(self):
        self.prepare(spec_data(outputs=[('result.json', 'json')], expected={'result.json': {'count': 2}}))
        rejected = {'path': absolute_alias(self.work, 'result.json'), 'content': '{"count":3}'}
        self.assertIn('proposal_validation_failed', self.call('write_file', rejected))
        self.assertEqual(self.effects, [])
        self.assertEqual(self.owned.checkpoint.state['validation_rejections'][0]['args'], rejected)
        self.release(); self.claim()
        self.assertTrue(rec.resumable(self.owned, self.db, self.work))
        self.call('write_file', {'path': './result.json', 'content': '{"count":2}'})
        self.finish()
        self.assertEqual(len(self.effects), 1)
        completion = self.spec.completion(self.work, self.owned.checkpoint.state['tools'], 'done')
        self.assertEqual(completion['semantic_validation'], 'oracle_matched')

    def test_uncertain_absolute_write_reconciles_and_reuses_without_second_effect(self):
        self.prepare()
        def barrier(label):
            if label == 'uncertain_after_write': raise rec.RecoveryStop('bounded synthetic interruption')
        self.controller.barrier = barrier
        args = {'path': absolute_alias(self.work, 'answer.txt'), 'content': 'Saved once.'}
        with self.assertRaises(rec.RecoveryStop): self.call('write_file', args, flush=False)
        operation_id = self.owned.checkpoint.operation['id']
        self.release(); self.claim()
        self.assertTrue(self.owned.checkpoint.requires_reconciliation)
        self.db.acquire_session_turn_lease = lambda *args, **kwargs: True
        self.db.release_session_turn_lease = lambda *args, **kwargs: None
        self.db.append_message = lambda session, role, **kwargs: self.db.append({
            'role': role, 'content': kwargs['content'], 'tool_call_id': kwargs['tool_call_id']})
        receipt = json.loads((self.run / 'effect-receipts.jsonl').read_text())
        self.assertEqual(receipt['args'], args)
        rec.reconcile_write(self.owned, self.db, self.work, receipt, expected_operation_id=operation_id)
        self.assertTrue(rec.resumable(self.owned, self.db, self.work))
        self.call('write_file', {'path': 'answer.txt', 'content': args['content']})
        self.assertEqual(len(self.effects), 1)
        self.assertEqual(len((self.run / 'effect-receipts.jsonl').read_text().splitlines()), 1)
        self.finish()

    def test_equal_reconstructed_validator_admitted_then_bound_to_exact_owned_spec(self):
        self.prepare()
        equal = TaskSpec(self.spec.data)
        self.controller = rec.Recovery(self.owned, self.db, self.work, self.run,
            controls=SimpleNamespace(poll=lambda owned: None),
            pre_effect_validator=equal.validate_write, validator_identity=equal.validator_identity())
        self.assertIsNot(equal, self.controller.task_spec)
        self.assertIs(self.controller.pre_effect_validator.__self__, self.controller.task_spec)
        self.assertIs(self.controller.pre_effect_validator.__func__, TaskSpec.validate_write)
        self.call('write_file', {'path': absolute_alias(self.work, 'answer.txt'), 'content': 'Summary.'})
        self.finish()

    def test_replacement_binding_and_invalid_callback_identity_pair_refused(self):
        self.prepare()
        with self.assertRaises(ValueError):
            rec.Recovery(self.owned, self.db, self.work, self.run,
                pre_effect_validator=None, validator_identity=self.spec.validator_identity())
        self.controller.pre_effect_validator = TaskSpec(self.spec.data).validate_write
        response = self.call('write_file', {'path': './answer.txt', 'content': 'Summary.'}, flush=False)
        self.assertIn('error', json.loads(response))
        self.assertIsNotNone(self.controller.fatal)
        self.assertEqual(self.effects, [])

    def test_removing_declared_validator_cannot_bypass_binding_guard(self):
        self.prepare()
        self.controller.pre_effect_validator = None
        response = self.call('write_file', {'path': './answer.txt', 'content': 'Summary.'}, flush=False)
        self.assertIn('error', json.loads(response))
        self.assertIsNotNone(self.controller.fatal)
        self.assertEqual(self.effects, [])


if __name__ == '__main__':
    unittest.main()
