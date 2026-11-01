"""Pure budget-policy checks; no boot observation, persistence or model execution."""
from copy import deepcopy
import unittest

from adaptive_inference.desktop.execution_budget import (
    BudgetError, create_budget, reopen_budget, tighten_budget, validate_budget,
)

NS = 1_000_000_000
UTC = 1_793_568_000 * NS
A, B, C = 'a' * 64, 'b' * 64, 'c' * 64


def observed(utc_seconds, before, after=None):
    return {'utc_ns': UTC + utc_seconds * NS, 'qpc_before': before,
            'qpc_after': before if after is None else after}


class ExecutionBudgetTests(unittest.TestCase):
    def new(self):
        return create_budget(boot_id=A, deadline=1000, observation=observed(0, 100, 102))

    def stopped(self):
        return tighten_budget(self.new(), boot_id=A, observation=observed(200, 300, 302))

    def test_initial_budget_accounts_for_existing_grant_and_bracket(self):
        value = self.new()
        self.assertEqual(value['expires_utc_ns'], UTC + 898 * NS)
        self.assertEqual(value['remaining_cap_ns'], 898 * NS)
        self.assertEqual(value['episode']['deadline'], 1000)
        self.assertFalse(value['clean_stop'])
        for deadline in (102, 1003):
            with self.subTest(deadline=deadline), self.assertRaises(BudgetError):
                create_budget(boot_id=A, deadline=deadline, observation=observed(0, 100, 102))

    def test_clean_stop_changed_boot_then_delayed_same_boot_reopen(self):
        original = self.new(); frozen = deepcopy(original)
        stopped = tighten_budget(original, boot_id=A, observation=observed(200, 300, 302))
        self.assertEqual(original, frozen)
        self.assertEqual(stopped['remaining_cap_ns'], 698 * NS)
        restarted = reopen_budget(stopped, boot_id=B, observation=observed(300, 10, 12))
        self.assertEqual(stopped['clean_stop'], True)
        self.assertEqual(restarted['origin'], original['origin'])
        self.assertEqual(restarted['expires_utc_ns'], original['expires_utc_ns'])
        self.assertEqual(restarted['episode']['index'], 1)
        self.assertEqual(restarted['episode']['deadline'], 608)
        self.assertEqual(restarted['remaining_cap_ns'], 596 * NS)
        self.assertFalse(restarted['clean_stop'])
        delayed = reopen_budget(restarted, boot_id=B, observation=observed(330, 40, 42))
        self.assertEqual(delayed['episode'], restarted['episode'])
        self.assertEqual(delayed['remaining_cap_ns'], 566 * NS)
        self.assertEqual(delayed['expires_utc_ns'], original['expires_utc_ns'])

    def test_execution_consumes_clean_stop_on_same_boot_and_changed_boot(self):
        stopped = self.stopped()
        same = reopen_budget(stopped, boot_id=A, observation=observed(210, 310, 312))
        self.assertEqual(same['episode']['deadline'], 1000)
        self.assertFalse(same['clean_stop'])
        with self.assertRaisesRegex(BudgetError, 'clean Stop'):
            reopen_budget(same, boot_id=B, observation=observed(220, 1, 2))
        changed = reopen_budget(stopped, boot_id=B, observation=observed(210, 1, 2))
        with self.assertRaisesRegex(BudgetError, 'clean Stop'):
            reopen_budget(changed, boot_id=C, observation=observed(220, 1, 2))
        stopped_again = tighten_budget(changed, boot_id=B, observation=observed(220, 11, 12))
        next_boot = reopen_budget(stopped_again, boot_id=C, observation=observed(230, 1, 2))
        self.assertEqual(next_boot['episode']['index'], 2)
        self.assertLess(next_boot['remaining_cap_ns'], stopped_again['remaining_cap_ns'])
        self.assertEqual(next_boot['expires_utc_ns'], stopped['expires_utc_ns'])

    def test_expiry_rollback_and_wrong_stop_boot_refuse(self):
        stopped = self.stopped()
        for boot, stamp in ((B, observed(898, 1, 2)), (B, observed(199, 1, 2)),
                            (A, observed(201, 299, 301)), (A, observed(900, 1000, 1002))):
            with self.subTest(boot=boot, stamp=stamp), self.assertRaises(BudgetError):
                reopen_budget(stopped, boot_id=boot, observation=stamp)
        with self.assertRaisesRegex(BudgetError, 'current boot'):
            tighten_budget(stopped, boot_id=B, observation=observed(210, 1, 2))
        expired = tighten_budget(stopped, boot_id=A, observation=observed(900, 1000, 1002))
        self.assertEqual(expired['remaining_cap_ns'], 0)
        with self.assertRaises(BudgetError):
            reopen_budget(expired, boot_id=B, observation=observed(901, 1, 2))

    def test_budget_validation_rejects_refund_or_expiration_replacement(self):
        original = self.stopped()
        for key, value in (('expires_utc_ns', original['expires_utc_ns'] + NS),
                           ('remaining_cap_ns', original['remaining_cap_ns'] + NS),
                           ('max_seconds', 1800)):
            damaged = deepcopy(original); damaged[key] = value
            with self.subTest(field=key), self.assertRaises(BudgetError):
                validate_budget(damaged)
        changed = reopen_budget(original, boot_id=B, observation=observed(300, 10, 12))
        changed['episode']['deadline'] += 1
        with self.assertRaisesRegex(BudgetError, 'refunded'):
            validate_budget(changed)

    def test_legacy_absence_is_never_retrofitted_and_validation_copies(self):
        for legacy in (None, {}, {'deadline_monotonic': 1000}):
            with self.subTest(legacy=legacy), self.assertRaises(BudgetError):
                validate_budget(legacy)
        value = self.stopped(); copied = validate_budget(value)
        copied['episode']['deadline'] = 3
        self.assertEqual(value['episode']['deadline'], 1000)


if __name__ == '__main__':
    unittest.main()
