"""Behavioral budget cases, including medking82/Strata #3684 regressions.

Upstream arithmetic cases: f273ef65e8f4548125f3e72833cd61019b82080f,
apps/host/tests/harness-budget.test.mjs (MIT; third_party/strata/LICENSE).
The unchanged-cap, exact-compaction and refusal contracts are specific to this
host helper. No tokenizer, backend or model is substituted by these tests.
"""

from dataclasses import FrozenInstanceError
import unittest

from adaptive_inference.context_budget import plan_context_budget


class ContextBudgetTests(unittest.TestCase):
    def plan(self, window=8192, prompt=6545, output=4096, **kwargs):
        return plan_context_budget(context_tokens=window, prompt_tokens=prompt,
                                   required_output_tokens=output, **kwargs)

    def test_small_context_regression_preserves_requested_output(self):
        # Upstream fixed-4096 clamp would issue one token here. The adaptive
        # margin allows 1135, but the host still requested 4096, so compact.
        self.assertEqual(max(1, 8192 - 6545 - 4096), 1)
        plan = self.plan()
        self.assertEqual(plan.safety_tokens, 512)
        self.assertEqual(plan.available_output_tokens, 1135)
        self.assertEqual(plan.required_output_tokens, 4096)
        self.assertEqual(plan.status, "needs_compaction")
        self.assertEqual(plan.prompt_target_tokens, 3584)
        self.assertEqual(plan.tokens_to_remove, 2961)

    def test_declared_small_output_is_ready_without_inventing_a_larger_cap(self):
        for cap in [1, 128, 1135]:
            with self.subTest(cap=cap):
                plan = self.plan(output=cap)
                self.assertEqual(plan.status, "ready")
                self.assertEqual(plan.required_output_tokens, cap)
                self.assertEqual(plan.tokens_to_remove, 0)

    def test_tool_followup_leaves_half_the_remaining_small_window(self):
        for prompt, available in [(7750, 221), (8000, 96)]:
            with self.subTest(prompt=prompt):
                plan = self.plan(prompt=prompt, output=available)
                self.assertEqual(plan.available_output_tokens, available)
                self.assertEqual(plan.status, "ready")
                bigger = self.plan(prompt=prompt, output=available + 1)
                self.assertEqual(bigger.status, "needs_compaction")
                self.assertEqual(bigger.required_output_tokens, available + 1)

    def test_compaction_target_recomputes_margin_instead_of_subtracting_deficit(self):
        plan = self.plan(prompt=8000, output=500)
        self.assertEqual(plan.available_output_tokens, 96)
        self.assertEqual(plan.prompt_target_tokens, 7193)
        self.assertEqual(plan.tokens_to_remove, 807)
        self.assertEqual(self.plan(prompt=7193, output=500).status, "ready")
        self.assertEqual(self.plan(prompt=7194, output=500).status, "needs_compaction")

    def test_32k_and_64k_boundary_match_upstream_margin_policy(self):
        for window, safety, available in [(32768, 2048, 24175),
                                          (65536, 4096, 54895),
                                          (131072, 4096, 120431)]:
            with self.subTest(window=window):
                plan = self.plan(window=window, output=128)
                self.assertEqual((plan.safety_tokens, plan.available_output_tokens),
                                 (safety, available))
        self.assertEqual(self.plan(window=65535, prompt=65000, output=1).safety_tokens, 267)
        self.assertEqual(self.plan(window=65536, prompt=65000, output=1).safety_tokens, 4096)

    def test_full_or_overfull_prompt_never_fabricates_one_token_of_room(self):
        for prompt in [8192, 9000]:
            with self.subTest(prompt=prompt):
                plan = self.plan(prompt=prompt, output=1)
                self.assertEqual(plan.available_output_tokens, 0)
                self.assertEqual(plan.status, "needs_compaction")
                self.assertEqual(plan.prompt_target_tokens, 8191)

    def test_impossible_generation_reports_no_room_not_a_reduced_output(self):
        for window, output in [(8192, 7681), (65536, 61441), (8192, 9000)]:
            with self.subTest(window=window, output=output):
                plan = self.plan(window=window, prompt=0, output=output)
                self.assertEqual(plan.status, "no_room")
                self.assertIsNone(plan.prompt_target_tokens)
                self.assertIsNone(plan.tokens_to_remove)
                self.assertEqual(plan.required_output_tokens, output)

    def test_reasoning_and_answer_reservations_are_included_not_double_counted(self):
        plan = self.plan(window=65536, prompt=50000, output=10923,
                         reasoning_tokens=8192, answer_tokens=2731)
        self.assertEqual(plan.status, "ready")
        self.assertEqual(plan.required_output_tokens, 10923)
        self.assertEqual((plan.reasoning_tokens, plan.answer_tokens), (8192, 2731))
        self.assertEqual(plan.prompt_target_tokens, 50517)
        with self.assertRaisesRegex(ValueError, "exceeds"):
            self.plan(output=10923, reasoning_tokens=8192, answer_tokens=2732)

    def test_unknown_malformed_and_fractional_counts_fail_closed(self):
        valid = dict(context_tokens=8192, prompt_tokens=6545, required_output_tokens=4096,
                     reasoning_tokens=0, answer_tokens=0)
        for field in valid:
            for value in [None, True, False, -1, 1.5, float("nan"), float("inf"), "8192", [], {}]:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    plan_context_budget(**{**valid, field: value})
        for field in ["context_tokens", "required_output_tokens"]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                plan_context_budget(**{**valid, field: 0})

    def test_plan_is_immutable(self):
        plan = self.plan()
        with self.assertRaises(FrozenInstanceError):
            plan.required_output_tokens = 1

    def test_target_is_maximal_and_ready_after_recount_across_windows(self):
        # Boundary and saturation cases verify the decision contract without
        # merely duplicating the implementation's arithmetic or binary search.
        for window in [1, 15, 16, 32, 512, 8192, 32768, 65535, 65536, 131072]:
            for cap in sorted({1, max(1, window // 8), max(1, window // 2), window}):
                with self.subTest(window=window, cap=cap):
                    plan = self.plan(window=window, prompt=window + 77, output=cap)
                    if plan.status == "no_room":
                        self.assertEqual(self.plan(window=window, prompt=0, output=cap).status, "no_room")
                        continue
                    self.assertEqual(plan.status, "needs_compaction")
                    target = plan.prompt_target_tokens
                    self.assertEqual(self.plan(window=window, prompt=target, output=cap).status, "ready")
                    self.assertEqual(self.plan(window=window, prompt=target + 1, output=cap).status,
                                     "needs_compaction")
                    self.assertEqual(plan.tokens_to_remove, window + 77 - target)


if __name__ == "__main__":
    unittest.main()
