# SPDX-License-Identifier: Apache-2.0
"""Explicit fresh-task opt-in and cooperative owner waits; no model/agent launch."""
import time

from adaptive_inference.demand import DemandIdentity, NAMESPACE, _record
from adaptive_inference.task_store import ReconciliationRequired
from adaptive_inference.control_mailbox import Mailbox, execution_outcome
from adaptive_inference.desktop.hermes.recovery import ControlStop, initial_state


def prepare_task(store, identity, prompt, session_id, *, metadata, max_attempts=8):
    """Create immutable demand identity with the original task, never retrofit."""
    if type(identity) is not DemandIdentity or type(metadata) is not dict or NAMESPACE in metadata:
        raise ValueError('Fresh explicit identity and identity-free host metadata required')
    return store.create(identity.task_id, prompt, max_attempts=max_attempts,
        metadata={**metadata, NAMESPACE: identity.metadata()}, state=initial_state(prompt, session_id))


class Controls:
    def __init__(self, mailbox, *, deadline, utc_now, clock=time.monotonic, sleep=time.sleep,
                 safe_boundary=None):
        if type(mailbox) is not Mailbox:
            raise TypeError('Reviewed trusted mailbox required')
        self.mailbox = mailbox
        self.deadline, self.utc_now, self.clock, self.sleep = deadline, utc_now, clock, sleep
        if safe_boundary is not None and not callable(safe_boundary):
            raise TypeError('Explicit synchronous owner-safe callback required')
        self.safe_boundary = safe_boundary
        self.paused_expiry_observation = None

    def bootstrap(self, owned):
        if execution_outcome(owned.checkpoint.state) is not None:
            raise ReconciliationRequired('This execution budget is sealed')
        if owned.checkpoint.operation or owned.checkpoint.requires_reconciliation:
            raise ReconciliationRequired('Bootstrap cannot replay unknown execution')
        # Consume previously recorded controls before making absent demand
        # eligible. Any interrupted transition/ACK propagates: do not activate
        # around it or let a cold host observe transient waiting demand.
        self.mailbox.consume(owned,updated_at_utc=self.utc_now())
        record = _record(owned.checkpoint, self.mailbox.identity)
        if record is None:
            self.mailbox.registry.transition(self.mailbox.identity.registration_id,owned,'waiting',
                expected_revision=owned.checkpoint.revision,updated_at_utc=self.utc_now(),
                reason='trusted host bootstrap before readiness')
        return self.poll(owned)

    def poll(self, owned):
        while True:
            if execution_outcome(owned.checkpoint.state) is not None:
                self.paused_expiry_observation = None
                raise ReconciliationRequired('This execution budget is sealed')
            boundary = self.mailbox.consume(owned,updated_at_utc=self.utc_now())
            if self.safe_boundary is not None:
                self.safe_boundary(owned, boundary)
            if boundary['allowed']:
                self.paused_expiry_observation = None
                if self.clock() >= self.deadline:
                    raise ControlStop('active', 'control_wait_deadline')
                return boundary
            state = _record(owned.checkpoint,self.mailbox.identity)
            state = None if state is None else state['state']
            if boundary['reason'] == 'operation_inflight_or_reconciliation':
                self.paused_expiry_observation = None
                raise ReconciliationRequired('Control requested during unresolved operation')
            if state in ('cancelled','fulfilled'):
                self.paused_expiry_observation = None
                raise ControlStop(state,'durable_control_acknowledged')
            if state != 'paused' and boundary['reason'] != 'pending_control':
                self.paused_expiry_observation = None
                raise ReconciliationRequired('No trusted demand authorizes further work')
            if state == 'paused' and boundary['reason'] == 'demand_paused' and boundary['pending'] == 0:
                try:
                    observation = self.mailbox.paused_execution_observation(owned)
                except BaseException:
                    self.paused_expiry_observation = None
                    raise
                # The timestamp follows the coherent read. A slow read cannot
                # turn a newly observed late Pause into a pre-deadline boundary.
                observed_at = self.clock()
                previous = self.paused_expiry_observation
                if previous is None or previous['pause'] != observation:
                    self.paused_expiry_observation = None
                    if observed_at < self.deadline:
                        self.paused_expiry_observation = {'pause': observation, 'observed_at': observed_at}
            else:
                self.paused_expiry_observation = None
            if self.clock() >= self.deadline:
                raise ControlStop(state or 'pending','control_wait_deadline')
            self.sleep(min(.25,max(0,self.deadline-self.clock())))
