# Waiting for resources without losing an agent task

An always-on agent must distinguish two situations: the controller has not
started a model request because the person needs the computer, and a model
request started but its outcome is unknown. Only the first situation permits
automatic resubmission on the strength of an admission receipt.

For example, an agent may have finished reading a spreadsheet when the user
starts a demanding application. The agent should retain the spreadsheet result
and wait before asking the model for its next step. It should not hold an open
model connection until the agent's provider watchdog mistakes the intentional
wait for a broken server. It also must not rerun a completed file write merely
because the connection failed later.

## Optional immediate admission

Ordinary gateway clients retain the existing bounded queue. A compatible agent
may instead send both headers on a generation request:

```text
X-Adaptive-Admission: immediate
X-Adaptive-Attempt-Id: a-unique-client-attempt
```

The scheduler makes one atomic decision using its existing capacity gate,
active-owner check and ordering rule. It either claims the dispatch slot or
returns a complete 503 response with error code `admission_deferred`. A deferred
request leaves no pending ticket, reaches no backend and contributes no timing
sample to the learned request-cost model. This is an opt-in transport feature;
the headers do not change the model, prompt or generation settings.

Only that pre-dispatch refusal carries all of these response headers:

```text
X-Adaptive-Dispatch: not-dispatched
X-Adaptive-Gateway-Instance: <instance from this gateway's status>
X-Adaptive-Attempt-Id: <the submitted attempt>
X-Adaptive-Body-SHA256: <SHA-256 of the exact submitted HTTP body bytes>
```

The JSON `admission` object repeats the instance, attempt and body hash and sets
`dispatched` to `false`. Backend response headers cannot supply this proof: the
gateway's backend-response allowlist excludes these admission headers. Invalid
input, shutdown, uncertain backend completion and ordinary backend errors do not
receive this proof.

An attempt identifier is for matching evidence, not an idempotency key. The
gateway does not promise exactly-once generation if a client independently
submits the same attempt twice. After a deferral, the next attempt is a new
arrival under the same ordering rule and has no reserved queue position.

## Compatible agent behavior

The agent waits outside its provider-call watchdog and within a declared overall
task deadline. A readiness check can avoid unnecessary attempts, but is not a
reservation. If foreground activity changes between that check and the atomic
claim, the complete non-dispatch receipt makes the race explicit.

The agent must disable ordinary provider retries and fallbacks for this
integration. Automatic resubmission requires the complete matching response:
status, error type and code, dispatch marker, gateway instance, attempt identity,
and exact body hash. A timeout, truncated response, connection loss, generic 503
or an upstream response that merely contains similar text is insufficient.
Once a request has been admitted, later foreground activity follows the normal
drain-and-release contract; it does not make the generation safe to replay.

The durable task record retains the original objective, native conversation,
completed tool receipts and any unresolved operation. A known non-dispatch can
return to resource waiting. Unknown execution requires reconciliation before
another worker continues. Resource waiting does not establish exactly-once
effects for arbitrary tools.

## Evidence boundary

This protocol was introduced after a real installed-Hermes trial exposed a
180-second stale-provider watchdog while the gateway intentionally held a
request for foreground activity. That trial's foreground and GPU handoff
receipts do not make its failed agent-recovery phase a success. A fresh
[complete successor](../provenance/windows-handoff/controlled-11/README.md)
passes independent acceptance, including one worker restart and an 81.375-second
observed wait during release/restoration following foreground demand. That wait
starts after the visible window ends and is shorter than 180 seconds. The
separate synthetic long-wait fixture is not a real elapsed-time qualification.

The implementation is in [the scheduler](../src/adaptive_inference/scheduler.py)
and [the gateway](../src/adaptive_inference/gateway.py). The existing
[native handoff contract](automatic-handoff.md) and
[task-survival contract](task-survival.md) remain separate requirements.
