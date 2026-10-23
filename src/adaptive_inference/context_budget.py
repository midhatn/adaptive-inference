"""Explicit host-side context planning; never changes a request or its quality.

The safety-margin arithmetic adapts medking82's Strata PR #3684, MIT licensed:
https://github.com/medking82/Strata/blob/f273ef65e8f4548125f3e72833cd61019b82080f/apps/desktop/scripts/harness-budget.mjs
Copyright (c) 2026 Niko1221 and the Strata contributors; see
third_party/strata/LICENSE. The feasibility decisions and prompt target below
are new: unlike the upstream clamp, no output cap is reduced and no artificial
one-token request is allowed when the context has no room.

Callers must supply the effective context and complete rendered prompt count,
including tools, templates and any multimodal tokens. This module does not
tokenize, discover a model, infer an effort-to-token mapping, or attest that a
count is accurate. A ready plan is arithmetic feasibility, not runtime admission
or a guarantee that the model will produce the desired answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


BudgetStatus = Literal["ready", "needs_compaction", "no_room"]


@dataclass(frozen=True, slots=True)
class ContextBudgetPlan:
    context_tokens: int
    prompt_tokens: int
    required_output_tokens: int
    reasoning_tokens: int
    answer_tokens: int
    safety_tokens: int
    available_output_tokens: int
    status: BudgetStatus
    prompt_target_tokens: int | None
    tokens_to_remove: int | None


def _tokens(name: str, value: int, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0):
        adjective = "positive" if positive else "nonnegative"
        raise ValueError(f"{name} must be a {adjective} integer token count")
    return value


def _room(context: int, prompt: int) -> tuple[int, int]:
    remaining = context - prompt
    # Reused small-window margin, including the original 64K boundary.
    safety = 4096 if context >= 65536 else min(
        4096, context // 16, max(0, remaining // 2)
    )
    return safety, max(0, remaining - safety)


def plan_context_budget(
    *, context_tokens: int, prompt_tokens: int, required_output_tokens: int,
    reasoning_tokens: int = 0, answer_tokens: int = 0,
) -> ContextBudgetPlan:
    """Plan room for the unchanged total output ceiling chosen by the host.

    ``required_output_tokens`` includes reasoning; the explicit reasoning and
    answer reservations must sum to no more than that total. They are recorded
    unchanged, never added to the ceiling again or derived from an effort label.
    Zero reservations mean unspecified, not that reasoning or answers are off.
    A host using separate backend ceilings must first express a truthful shared
    total; this helper does not translate backend semantics.

    ``ready`` means the present count fits. ``needs_compaction`` supplies the
    largest prompt count that fits the same output ceiling under this policy;
    the host must compact and recount before dispatch. ``no_room`` means even
    an empty prompt cannot fit, so compaction alone cannot satisfy the policy.
    None denotes an impossible target, rather than a zero-token generation.

    The adaptive safety margin is a heuristic for host planning, not a certified
    error bound for an approximate tokenizer. Use the engine's full rendered
    count and its own final admission check before making an actual request.
    """
    context = _tokens("context_tokens", context_tokens, positive=True)
    prompt = _tokens("prompt_tokens", prompt_tokens)
    required = _tokens("required_output_tokens", required_output_tokens, positive=True)
    reasoning = _tokens("reasoning_tokens", reasoning_tokens)
    answer = _tokens("answer_tokens", answer_tokens)
    if reasoning + answer > required:
        raise ValueError("reasoning_tokens + answer_tokens exceeds required_output_tokens")

    safety, available = _room(context, prompt)
    if _room(context, 0)[1] < required:
        status: BudgetStatus = "no_room"
        target = remove = None
    else:
        # Room decreases monotonically with prompt length, despite the changing
        # small-context margin. Search the exact boundary, not an assumed fixed
        # margin: subtracting the current deficit can under-compact near 8K.
        low, high = 0, context
        while low < high:
            middle = (low + high + 1) // 2
            if _room(context, middle)[1] >= required:
                low = middle
            else:
                high = middle - 1
        target = low
        remove = max(0, prompt - target)
        status = "ready" if available >= required else "needs_compaction"
    return ContextBudgetPlan(context, prompt, required, reasoning, answer,
                             safety, available, status, target, remove)
