# Durable inference demand — component in development

This component records whether an explicitly registered task still
needs inference. It uses the existing Adaptive Inference `TaskStore` and
`OwnedTask`, including their transaction, revision, process-ownership and
interrupted-operation checks. It creates no second database. It is not yet
wired to a persistent controller, native startup or the existing task runner.
The component tests do not complete M2 or qualify M1 foreground handoff.

## Why a separate demand record is useful

An immediate-admission request can be deferred without entering an HTTP queue.
Its agent then waits outside provider execution. If model restoration waits
only for a queued HTTP ticket, both sides can wait indefinitely. This record
expresses a task's need independently of the HTTP queue. It does not restore a
model, reserve capacity, grant a resource lease or dispatch anything.

## Contract

- A trusted host creates `DemandIdentity`, places its `metadata()` under
  `adaptive_inference.demand.v1` in immutable `TaskStore.create` metadata, and
  supplies an explicit `Registration(store, identity)` to `DemandRegistry`.
  Reconstruct these exact bindings from trusted settings after host restart.
  There is no database scanning, arbitrary caller path or HTTP-header authority.
- `transition` requires the actual claimed `OwnedTask` and its current revision.
  It checks the registered store, task and immutable identity. Every write uses
  `OwnedTask.save_checkpoint`; no raw SQL, replacement owner lock or second
  journal is introduced. A read transaction calls the existing internal owner
  fence for same-state no-ops; this version-sensitive dependency is covered by
  the demand and TaskStore tests and must be rechecked when TaskStore changes.
- One record covers the task's lifetime. `active` and `waiting` express demand;
  they may span several model calls. `paused` is resumable. `cancelled` and
  `fulfilled` are terminal demand states. Fulfilled means the task's inference
  need is finished, not that its first model request returned. Per-request
  demand cycles are deliberately outside this component. These terminal values
  affect only the namespaced demand record. The existing task runner does not
  yet check them: they do not make the underlying task terminal or stop native
  execution, and they are not evidence of native cancellation.
- `observe` reads registered checkpoints without taking the writer lock or
  incrementing revisions. Safe active/waiting demand can be eligible without
  any HTTP ticket. An accepted/exhausted task, unresolved operation,
  reconciliation requirement, malformed record or unreadable checkpoint is
  ineligible. A result can immediately become stale: it is an advisory signal,
  never permission to dispatch or replay a tool/effect.
  Eligibility is only an advisory candidate for future demand-aware restoration.
  False for in-flight or unknown state is not absence of resource ownership and
  must never authorize unloading an active model. Existing scheduler/native
  drain and release checks remain the authority.
  Persisted eligible demand is not proof of a live runner or permission to
  dispatch, and it must not keep a model resident indefinitely. A future
  controller still needs bounded demand handling and its normal resource gates.
- Cancellation is durably recorded only at a safe checkpoint through its owner.
  This does not interrupt an executing generation/tool or bypass reconciliation.
  Messaging a live owner and cancelling native startup are later work.
- A stable logical `owner_id` describes host/agent lineage; it is not an OS PID,
  credential, mutable ownership epoch or proof that a runner is alive.
- Original arrival is immutable explicit UTC text, preserved across claims,
  waiting, pause/resume and reopening. Updated timestamps are also UTC text.
  No monotonic value is persisted or compared across boots, and no timestamp
  grants eligibility. Clock changes do not create execution permission. Actual
  fairness/elapsed-budget accounting across clock changes is future work.
- Same-state calls validate ownership and revision but do not rewrite reason or
  timestamp. Polling calls `observe`; it does not consume the store's finite
  revision or attempt budgets. Actual state changes and new owner claims still
  consume the existing 256-revision limit; this component does not claim unlimited
  transitions or silently change retention limits.
- Cooperating callers must use this transition helper for the demand namespace.
  It is not a security boundary against arbitrary checkpoint/database changes by
  the same user. Pending demand may remain eligible after the old claim ends so
  a replacement worker can discover it; a closed `OwnedTask` cannot write, and
  a terminal task always overrides its demand record.

## Minimal trusted-host usage

```python
from adaptive_inference.task_store import TaskStore
from adaptive_inference.demand import DemandIdentity, DemandRegistry, NAMESPACE, Registration

# These values come from stable trusted host settings, not request headers.
store = TaskStore(private_task_database)
identity = DemandIdentity("report-demand", "report", "host-agent-root", arrival_utc)

# Create once. After restart, reopen the existing store and restore the exact
# original identity/arrival from trusted settings rather than recreating it.
checkpoint = store.create("report", original_prompt, max_attempts=3,
                          metadata={NAMESPACE: identity.metadata()})
registry = DemandRegistry((Registration(store, identity),))
with store.claim("report", expected_revision=checkpoint.revision,
                 owner_id="worker-instance") as owned:
    registry.transition("report-demand", owned, "waiting",
                        expected_revision=owned.checkpoint.revision,
                        updated_at_utc=now_utc)

# Read-only signal for a future controller; this does not execute anything.
observation = registry.observe("report-demand")
```

## Research consulted before implementation

The applicable official documentation and pinned source below were reviewed
before this implementation on 24 October 2026. These are design adaptations
using this project's existing task ledger;
no upstream executable implementation was copied.

- **KEDA demand activation, Apache-2.0 project:** separation of demand from
  inactivity/cooldown informs the independent demand signal. This component
  does not implement KEDA's timers or Kubernetes scaling.
  [Versioned specification](https://keda.sh/docs/2.21/reference/scaledobject-spec/),
  [inspected executor revision](https://github.com/kedacore/keda/blob/6016dc90a3fbca1c8cecbad37e50bd93f0badd7f/pkg/scaling/executor/scale_scaledobjects.go).
- **Temporal durable control/query semantics, MIT Python SDK:** separate
  observation and state-changing control, preserve durable waiting, and do not
  equate cancellation intent with stopping an effect.
  [Official message-passing documentation](https://docs.temporal.io/develop/python/workflows/message-passing),
  [inspected SDK revision](https://github.com/temporalio/sdk-python/blob/df8caecda503be16cdf54b136fcd1d40811df2dd/README.md).
- **Kueue explicit arrival/requeue accounting, Apache-2.0 project:** preserve
  original arrival across waiting instead of replacing it on every retry.
  This component implements no queue rank or quota reservation.
  [Inspected versioned readiness/requeue documentation](https://github.com/kubernetes-sigs/kueue/blob/1ec0d28ef62b4665a6e3db4ef594a86d0d458df6/site/content/en/v0.20/docs/tasks/manage/setup_wait_for_pods_ready.md).
- **Existing Adaptive Inference TaskStore:** reused directly. Its per-operation
  SQLite/revision pattern already credits medking82's Strata work under MIT;
  this component preserves that dependency and attribution rather than copying
  or replacing the storage implementation.
  [Attributed source](https://github.com/medking82/Strata/blob/64d119cd602ddc439c311dedf61fda460f2785ef/serve/chat_archive.py).

## CPU validation and remaining integration

From the repository root, use an environment with the project installed
(`python -m pip install -e .`) and run:

```text
python -m unittest discover -s tests -p test_demand.py -v
python -m unittest discover -s tests -p test_task_store.py -v
```

Tests use the real TaskStore and private temporary SQLite files, without a
server, model, provider, GPU or UI. The replacement-worker subprocess explicitly
loads this checkout's `src` directory instead of relying on its current directory.
The inspected canonical `task_store.py` SHA-256 is
`39f4efaa0983fea5202ac1027f12c7638787e7da874e26b678a9a3812b1afacc`.

The tests cover durable transitions, cancellation, pause, terminal states,
reconciliation, identity validation, stale revisions/owners, unchanged task
history/attempts and non-writing observation/idempotent calls. They are component
tests, not physical-reboot, persistent-host, native handoff or IQ3_S evidence.

Integration still needs host messaging/control, demand-aware cold startup and
restoration, foreground/feasibility gates, multiple-task coordination, native
cancellation reconciliation, bounded retention and real IQ3_S validation. A
controller must recheck relevant state and its existing native ownership and
capacity checks; it must never treat this predicate as a resource grant.
