# Task survival across application restarts

An always-on agent needs more than an open window or saved conversation. It needs to know its original objective, what it completed, what failed, and whether an interrupted action might already have happened. Adaptive Inference now provides a local checkpoint store and resumable feedback runner for that foundation.

The transaction/revision pattern is adapted from medking82's [Strata #1136](https://github.com/Niko1221/Strata/pull/1136), pinned to `serve/chat_archive.py` at `64d119cd602ddc439c311dedf61fda460f2785ef`. The [exact original source](../third_party/reference-sources/strata/64d119cd602ddc439c311dedf61fda460f2785ef/serve/chat_archive.py) is preserved locally. Its MIT license and credit are retained in the archive, [NOTICE](../NOTICE) and [REFERENCES.bib](../REFERENCES.bib). The original archive preserves conversations; our execution ledger, OS ownership and resumable runner are new additions.

## What is implemented

- A versioned SQLite store preserves the exact original prompt, immutable host identity metadata, attempt budget, messages, outputs, feedback, revisions and operation receipts.
- Transactions commit checkpoints atomically. Revision checks reject stale writers. Each task has an OS advisory lock held across its cooperating runner; a live owner prevents a second runner, and process termination releases that lock.
- `resume_with_feedback` saves generated text before validation and saves the validator's result before moving to the next attempt. A restarted host can continue from these committed boundaries, retaining the original task and earlier feedback.
- Accepted and exhausted tasks are terminal. Reopening a completed task returns its result without invoking generation or validation again.
- Interrupted generation, validation and external effects are recorded. Resume stops for explicit outcome reconciliation by default. A caller may opt into retrying an interrupted **pure text-generation** callback; the interrupted attempt still counts. That option never retries validation or effects.
- Foreign or corrupt stores are refused rather than reset. A recognized store can recover a hot SQLite rollback journal from an interrupted transaction. Unknown schema/version changes are not silently migrated.

The OS lock coordinates local runners that use this API. It does not stop an unrelated executor or prove whether an external action finished. Database transactions cannot make arbitrary external actions execute exactly once.

## Host integration

Create a task once using `TaskStore.create(task_id, prompt, max_attempts=..., metadata=...)`. On later starts, load the same task; do not replace its objective or reset its attempts. Store it in a private directory on a local filesystem, for example the ignored `local/` directory. Task content is saved as local plaintext, not automatically redacted or encrypted. Keep the database and its SQLite/lock sidecars together; do not delete lock files while runners may be alive.

Identity metadata must bind the generator/model configuration, validator and workflow versions used by the host. `resume_with_feedback` requires a nonempty identity object exactly matching that metadata. A changed identity requires an explicit host migration or reconciliation, not silent continuation under different settings.

The application supplies generation and validation callbacks:

```python
from adaptive_inference.feedback import resume_with_feedback
from adaptive_inference.task_store import TaskStore

store = TaskStore("local/tasks.sqlite3")  # Parent directory must already exist.
result = await resume_with_feedback(
    store, "existing-task-id", generate_text, validate_result,
    identity=declared_identity,
)
```

This fragment assumes the task was created and the host defined its callbacks. `generate_text(messages)` returns text; `validate_result(output)` returns `Verdict`. Both can be synchronous or asynchronous. No model-requested tool call is executed by this helper. An optional `on_checkpoint` observer runs after committed progress and can support status reporting or controlled suspension; it must not execute task effects.

For a real external action, a host acquires `store.claim(...)`, commits `begin_operation("effect", ...)` **before** dispatch, then calls `complete_operation(...)` with the observed result. If the owner dies between those points, the next owner must inspect the actual tool/job/artifact and use `reconcile_operation(...)` with explicit evidence. A tool's idempotency key or existing job identifier can help resolve the outcome. An ambiguous action remains blocked until the host can decide truthfully; it is not automatically repeated.

This is a library integration. The generic HTTP gateway does not secretly persist private conversations or execute/resume agent tools. Existing installations need an adapter to invoke these checkpoints and reconcile their tools. The pinned Hermes adapter below has one accepted [foreground/tool handoff and worker-restart workflow](../provenance/windows-handoff/controlled-11/README.md). Automatic OS login/startup, a real computer reboot, native KV restore and other agents remain separate acceptance work.

The optional [installed-Hermes adapter](../examples/validation/windows_handoff/hermes/README.md)
now implements those boundaries for a bounded native file task. It retains the
original objective and native conversation, verifies tool receipts before the
next model request, and resumes from the same SessionDB/TaskStore after process
termination. Changed artifacts and uncertain cross-database effects refuse
until explicit reconciliation. Its [automatic-handoff composition](automatic-handoff.md)
has separate software and hardware acceptance receipts. This does not install
OS startup hooks or extend the file-task receipt contract to arbitrary tools.

## Storage bounds

The store admits at most 1000 tasks, 256 revisions per task, 20 generation attempts, and 1 MiB per serialized record. The SQLite main-file limit is 64 MiB; rollback journals and lock sidecars use additional space, so this is not a total directory quota. Oversized records or exhausted capacity refuse atomically. The original prompt is limited to 256 KiB. These limits keep the initial implementation bounded; they are not a retention service or unlimited agent memory. A host must plan archive/rotation without discarding active task state.

SQLite uses full synchronous commits and rollback journaling. The tests establish the tested process-death behavior, not a universal guarantee against disk failure, lost storage or physical power interruption. Backups, storage reliability and deployment startup policy remain operational responsibilities.

## Reproduce process survival

```text
python -m unittest discover -s tests -p "test_task_store.py" -v
python -m unittest discover -s tests -p "test_persistent_feedback.py" -v
python -m unittest discover -s tests -p "test_restart_demo.py" -v
python examples/validation/restart_survival.py --output local/restart-proof-01
```

Choose a new output directory for each demonstration. Deterministic callbacks first create a wrong JSON inventory. Its rejected feedback is committed, the worker is terminated, and a new process continues to produce the independently checked total of 42 in two attempts. A competing live owner is refused, and reopening the accepted task executes no callbacks.

A second scenario appends one external-effect record, then terminates before acknowledgment. Two fresh resumes both stop for reconciliation; the record count remains one. Seven worker processes exit. Separate store tests interrupt an uncommitted SQLite write and verify that the previous state and revision history survive rollback recovery.

These are real process and disk-state tests with synthetic generation/tools. They are the durable foundation for agent survival, not a claim that an installed agent has already survived an OS reboot or completed the full always-on workflow.
