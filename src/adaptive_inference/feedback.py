"""Outcome-driven retries for applications with an explicit acceptance check.

The original task remains in the conversation. Only the caller's validator can
accept a result. Tools and side effects remain the calling agent's responsibility.
"""
from dataclasses import dataclass
import copy
import inspect


@dataclass(frozen=True)
class Verdict:
    accepted: bool
    feedback: str = ""


@dataclass(frozen=True)
class TaskResult:
    accepted: bool
    attempts: int
    output: str
    feedback: tuple[str, ...]


async def run_with_feedback(prompt, generate, validate, *, max_attempts=3):
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("An original task prompt is required")
    if type(max_attempts) is not int or not 1 <= max_attempts <= 20:
        raise ValueError("max_attempts must be between 1 and 20")
    messages = [{"role": "user", "content": prompt}]
    feedback = []
    for attempt in range(1, max_attempts + 1):
        output = generate(copy.deepcopy(messages))
        if inspect.isawaitable(output):
            output = await output
        if not isinstance(output, str):
            raise TypeError("generate must return text")
        verdict = validate(output)
        if inspect.isawaitable(verdict):
            verdict = await verdict
        if not isinstance(verdict, Verdict) or type(verdict.accepted) is not bool or not isinstance(verdict.feedback, str):
            raise TypeError("validate must return Verdict(accepted: bool, feedback: str)")
        if verdict.accepted:
            return TaskResult(True, attempt, output, tuple(feedback))
        feedback.append(verdict.feedback)
        messages.extend([{"role": "assistant", "content": output},
                         {"role": "user", "content": "The acceptance check failed. Correct the result while preserving the original task.\n" + verdict.feedback}])
    return TaskResult(False, max_attempts, output, tuple(feedback))
