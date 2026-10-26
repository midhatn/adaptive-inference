# SPDX-License-Identifier: Apache-2.0
"""Independent file-alias regressions through the public SQLite test helpers.

No SDK, model, native engine or GUI is executed. The Windows resolver
comparison reuses the documented operation in the retained Hermes source:
https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/tools/file_tools_paths.py
"""
from copy import deepcopy
import json
import ntpath
import os
from pathlib import Path
import unittest

import test_task_spec_recovery as baseline
from test_task_file_aliases import absolute_alias
from adaptive_inference.task_store import ReconciliationRequired
from adaptive_inference.task_spec import digest
from adaptive_inference.desktop.hermes import recovery as rec

class IndependentAliasTests(unittest.TestCase):
    setUp = baseline.TaskRecoveryTests.setUp
    prepare = baseline.TaskRecoveryTests.prepare
    claim = baseline.TaskRecoveryTests.claim
    release = baseline.TaskRecoveryTests.release
    call = baseline.TaskRecoveryTests.call

    def test_equivalent_path_does_not_replace_exact_native_intent(self):
        self.prepare()
        original = {'path': absolute_alias(self.work, 'answer.txt'), 'content': 'One effect.'}
        supplied = {'path': 'answer.txt', 'content': original['content']}
        self.db.append({'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': 'exact-intent', 'type': 'function', 'function': {
                'name': 'write_file', 'arguments': json.dumps(original)}}]})
        effects = []
        result = self.controller.tool('write_file', supplied, lambda args: effects.append(args),
            session_id='session', tool_call_id='exact-intent')
        self.assertEqual(effects, [])
        self.assertIn('error', json.loads(result))
        self.assertEqual(self.controller.fatal, 'ReconciliationRequired')
        self.assertFalse((self.work / 'answer.txt').exists())

    @unittest.skipUnless(os.name == 'nt', 'Native Windows path resolution comparison')
    def test_native_windows_lexical_resolution_matches_admitted_paths(self):
        self.prepare()
        for name in ('notes.txt', 'answer.txt'):
            aliases = [name, './' + name, '.\\' + name, str(self.work / name),
                absolute_alias(self.work, name), str(self.work / name).replace('\\', '/')]
            for raw in aliases:
                with self.subTest(raw=raw):
                    actual = self.spec.file_path(self.work, raw, write=name == 'answer.txt')
                    # Exact retained native _anchor win32 operation, without
                    # importing/constructing Hermes or executing a tool.
                    text = raw if ntpath.isabs(raw) else ntpath.join(str(self.work), raw)
                    self.assertEqual(Path(ntpath.normpath(text)), actual)

    def test_trailing_directory_syntax_and_noncanonical_capabilities_refuse(self):
        self.prepare()
        absolute = str(self.work / 'notes.txt')
        for raw in (absolute + '/', absolute + '\\', './notes.txt/', '.\\notes.txt\\',
                    './/../work/notes.txt', './NOTES.TXT', 'notes.txt.', 'notes.txt ',
                    '\\??\\' + absolute, '//?/' + absolute, absolute + ':$DATA'):
            with self.subTest(raw=raw), self.assertRaises((ValueError, OSError)):
                self.spec.file_path(self.work, raw)
        self.assertEqual(self.effects, [])

    def test_completion_checks_every_alias_receipt_hash(self):
        self.prepare()
        self.call('write_file', {'path': absolute_alias(self.work, 'answer.txt'), 'content': 'Saved.'})
        writes = deepcopy(self.owned.checkpoint.state['tools'])
        extra = deepcopy(writes[-1]); extra['args']['path'] = './answer.txt'
        extra['artifact_sha256'] = digest(b'not the artifact')
        writes.append(extra)
        with self.assertRaisesRegex(ValueError, 'differs from its durable write receipt'):
            self.spec.completion(self.work, writes, 'done')

    def test_alias_cannot_overwrite_previous_content(self):
        self.prepare()
        self.call('write_file', {'path': 'answer.txt', 'content': 'Saved.'})
        result = self.call('write_file', {'path': absolute_alias(self.work, 'answer.txt'),
            'content': 'Different.'}, flush=False)
        self.assertIn('error', json.loads(result))
        self.assertEqual((self.work / 'answer.txt').read_bytes(), b'Saved.')
        self.assertEqual(len(self.effects), 1)

    def test_absolute_read_cannot_bypass_changed_input(self):
        self.prepare()
        (self.work / 'notes.txt').write_bytes(b'changed input')
        result = self.call('read_file', {'path': absolute_alias(self.work, 'notes.txt')}, flush=False)
        self.assertIn('error', json.loads(result))
        self.assertEqual(self.effects, [])
        with self.assertRaises(ReconciliationRequired):
            rec.resumable(self.owned, self.db, self.work)

    def test_reused_logical_write_is_not_a_second_physical_effect(self):
        self.prepare()
        original = {'path': absolute_alias(self.work, 'answer.txt'), 'content': 'Saved once.'}
        retry = {'path': './answer.txt', 'content': original['content']}
        self.call('write_file', original)
        self.call('write_file', retry)
        logical = deepcopy(self.owned.checkpoint.state['tools'])
        physical = [json.loads(line) for line in (self.run / 'effect-receipts.jsonl').read_text().splitlines()]
        self.assertEqual(len(logical), 2)
        self.assertEqual(len(physical), 1)
        self.assertEqual(physical, [row for row in logical if row['reused'] is False])
        self.assertNotEqual(physical, logical)  # Logical retries are not additional physical writes.
        history = rec.native_history(self.db, 'session')
        for row in logical:
            calls = [c for h in history for c in h.get('tool_calls', []) if c['id'] == row['tool_call_id']]
            self.assertEqual(len(calls), 1)
            self.assertEqual(json.loads(calls[0]['function']['arguments']), row['args'])
        self.release(); self.claim()
        self.assertTrue(rec.resumable(self.owned, self.db, self.work))
        self.assertEqual(self.spec.completion(self.work, logical, 'done')['artifacts'],
            {'answer.txt': digest(b'Saved once.')})
