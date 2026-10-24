"""Independent CPU checks; real TaskStore, no model/native/UI/external effects."""
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

PROTOTYPE = Path(__file__).resolve().parents[1] / 'control-mailbox-prototype'
PINS = {
    'control_mailbox.py': '5084d3e0c3283c820680ccc683133f24ee050989caf67842eaee271cc56b798f',
    'test_control_mailbox.py': '4a32e95f35601144503547a6809bcabc1d3640cffe46f02e41ddbcac8ac1f7c1',
}
for name, expected in PINS.items():
    if hashlib.sha256((PROTOTYPE/name).read_bytes()).hexdigest() != expected:
        raise RuntimeError('Reviewed source changed: ' + name)
sys.path.insert(0, str(PROTOTYPE))
from test_control_mailbox import MailboxTests, NOW
from control_mailbox import ACKS, ControlBlocked
from adaptive_inference.task_store import OwnershipError


class IndependentBoundaryTests(unittest.TestCase):
    setUp = MailboxTests.setUp
    claim = MailboxTests.claim
    submit = MailboxTests.submit
    consume = MailboxTests.consume

    def test_ended_owner_cannot_acknowledge_after_replacement_claim(self):
        self.submit('cancel', 'cancel')
        with self.claim() as ended:
            pass
        with self.claim() as replacement:
            history = self.store.history('target')
            with self.assertRaises(OwnershipError):
                self.consume(ended)
            self.assertEqual(history, self.store.history('target'))
            self.assertEqual('pending', self.box.status('cancel')['outcome'])
            self.assertFalse(self.consume(replacement)['allowed'])
            self.assertEqual('applied', self.box.status('cancel')['outcome'])

    def test_active_validation_is_not_a_control_safe_point(self):
        with self.claim() as owned:
            running = owned.begin_operation('validation', details={'fixture_only': True},
                expected_revision=owned.checkpoint.revision)
            self.submit('pause', 'pause')
            history = self.store.history('target')
            boundary = self.consume(owned)
            self.assertFalse(boundary['allowed'])
            self.assertEqual('operation_inflight_or_reconciliation', boundary['reason'])
            self.assertEqual(history, self.store.history('target'))
            self.assertEqual(running.operation, owned.checkpoint.operation)
            self.assertFalse(self.box.status('pause')['owner_acknowledged'])
            owned.complete_operation(running.operation['id'], result={'fixture_complete': True},
                state=deepcopy(owned.checkpoint.state), expected_revision=owned.checkpoint.revision)
            self.assertFalse(self.consume(owned)['allowed'])
            self.assertTrue(self.box.status('pause')['owner_acknowledged'])

    def test_ack_failure_propagates_before_new_operation_is_started(self):
        self.submit('resume', 'resume')
        with self.claim() as owned:
            original = owned.save_checkpoint
            def fail_ack(state, **kwargs):
                if ACKS in state:
                    raise OSError('Independent fixture: ACK write unavailable')
                return original(state, **kwargs)
            with patch.object(owned, 'save_checkpoint', side_effect=fail_ack):
                with self.assertRaises(OSError):
                    self.box.begin_operation(owned, 'effect', updated_at_utc=NOW)
            self.assertIsNone(owned.checkpoint.operation)
            self.assertNotIn('operation_started', [row['event'] for row in self.store.history('target')])
            self.assertEqual('pending', self.box.status('resume')['outcome'])
            self.assertTrue(self.consume(owned)['allowed'])
            self.assertTrue(self.box.status('resume')['owner_acknowledged'])

    def test_command_appended_during_ack_is_pending_and_blocks_next_operation(self):
        self.submit('resume', 'resume')
        with self.claim() as owned:
            original = owned.save_checkpoint
            appended = False
            def append_after_ack(state, **kwargs):
                nonlocal appended
                saved = original(state, **kwargs)
                if ACKS in state and not appended:
                    appended = True
                    self.submit('cancel-later', 'cancel')
                return saved
            with patch.object(owned, 'save_checkpoint', side_effect=append_after_ack):
                boundary = self.consume(owned)
            self.assertFalse(boundary['allowed'])
            self.assertEqual('pending_control', boundary['reason'])
            self.assertEqual(1, boundary['pending'])
            self.assertIsNone(owned.checkpoint.operation)
            self.assertEqual('pending', self.box.status('cancel-later')['outcome'])
            with self.assertRaises(ControlBlocked):
                self.box.begin_operation(owned, 'generation', updated_at_utc=NOW)
            self.assertIsNone(owned.checkpoint.operation)
            self.assertTrue(self.box.status('cancel-later')['owner_acknowledged'])


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(IndependentBoundaryTests))
    raise SystemExit(not result.wasSuccessful())
