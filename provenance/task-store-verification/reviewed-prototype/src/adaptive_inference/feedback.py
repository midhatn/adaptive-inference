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


async def resume_with_feedback(store, task_id, generate, validate, *, identity,
                               retry_interrupted_generation=False, on_checkpoint=None):
    """Continue an explicitly created durable task under one local owner.

    ``identity`` must exactly match the task's nonempty metadata: callers bind
    generator/model, validator and workflow versions there. Generate returns
    text; validate returns Verdict. This helper executes no model-requested tool
    calls and does not authorize external actions. Their host needs its own
    operation ledger and outcome reconciliation.

    A completed generation is committed before validation. Rejected feedback is
    committed before the next attempt. An interrupted operation refuses resume
    by default. The explicit retry flag is only for generation callbacks known
    to have no external effects; the interrupted attempt still counts. Validation
    and effect operations always need explicit reconciliation through the store.

    ``on_checkpoint`` is an optional sync/async observer after a commit, useful
    for status or controlled suspension. It must not execute task effects. If it
    raises or the process exits, the committed checkpoint remains authoritative.
    The local OS task lock is held across the entire runner and is released on
    exit/process death; no lease expiry can start a second cooperating runner.
    """
    from .task_store import ReconciliationRequired

    if not isinstance(identity, dict) or not identity:
        raise ValueError("A nonempty generator/validator/workflow identity is required")
    if type(retry_interrupted_generation) is not bool:
        raise ValueError("retry_interrupted_generation must be a boolean")
    snapshot = store.load(task_id)
    if snapshot.metadata != identity:
        raise ValueError("Task identity differs; reconcile the workflow before resuming")

    async def call(function, *args):
        result = function(*args)
        return await result if inspect.isawaitable(result) else result

    async def committed(checkpoint):
        if on_checkpoint is not None:
            await call(on_checkpoint, copy.deepcopy(checkpoint))
        return checkpoint

    def result(checkpoint):
        state = checkpoint.state
        return TaskResult(state['status'] == 'accepted', state['attempts'],
                          state['output'], tuple(state['feedback']))

    with store.claim(task_id, expected_revision=snapshot.revision, owner_id='feedback-runner') as owned:
        checkpoint = owned.checkpoint
        if checkpoint.requires_reconciliation:
            operation = checkpoint.operation
            if not retry_interrupted_generation or operation['kind'] != 'generation':
                raise ReconciliationRequired("Interrupted operation requires explicit outcome reconciliation")
            state = copy.deepcopy(checkpoint.state)
            state['phase'] = 'ready'
            checkpoint = await committed(owned.retry_generation(operation['id'],
                        state=state, expected_revision=checkpoint.revision))
        while checkpoint.state['status'] == 'pending':
            state = copy.deepcopy(checkpoint.state)
            phase = state.get('phase', 'ready')
            if phase == 'ready':
                if state['attempts'] >= checkpoint.max_attempts:
                    state['status'] = 'exhausted'
                    checkpoint = await committed(owned.save_checkpoint(state, expected_revision=checkpoint.revision))
                    break
                state.update(attempts=state['attempts'] + 1, phase='generating', output='')
                checkpoint = owned.begin_operation('generation', state=state,
                            details={'attempt': state['attempts']}, expected_revision=checkpoint.revision)
                output = await call(generate, copy.deepcopy(state['messages']))
                if not isinstance(output, str):
                    raise TypeError("generate must return text")
                state.update(output=output, phase='awaiting_validation')
                checkpoint = await committed(owned.complete_operation(checkpoint.operation['id'],
                            result={'output': output}, state=state, expected_revision=checkpoint.revision))
            elif phase != 'awaiting_validation':
                raise ValueError("Task is not at a supported feedback checkpoint")

            state = copy.deepcopy(checkpoint.state)
            state['phase'] = 'validating'
            checkpoint = owned.begin_operation('validation', state=state,
                        details={'attempt': state['attempts']}, expected_revision=checkpoint.revision)
            verdict = await call(validate, state['output'])
            if (not isinstance(verdict, Verdict) or type(verdict.accepted) is not bool
                    or not isinstance(verdict.feedback, str)):
                raise TypeError("validate must return Verdict(accepted: bool, feedback: str)")
            state['phase'] = 'ready'
            if verdict.accepted:
                state['status'] = 'accepted'
            else:
                state['feedback'].append(verdict.feedback)
                state['messages'].extend([{'role': 'assistant', 'content': state['output']},
                         {'role': 'user', 'content': 'The acceptance check failed. Correct the result while preserving the original task.\n' + verdict.feedback}])
                if state['attempts'] >= checkpoint.max_attempts:
                    state['status'] = 'exhausted'
            checkpoint = await committed(owned.complete_operation(checkpoint.operation['id'],
                        result={'accepted': verdict.accepted, 'feedback': verdict.feedback},
                        state=state, expected_revision=checkpoint.revision))
        return result(checkpoint)
