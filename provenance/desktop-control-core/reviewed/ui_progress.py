# SPDX-License-Identifier: Apache-2.0
"""Opt-in host observations of the unchanged serialized GUI status path.

Completion is published only by SerialListener after handler and stream reaping.
Two completed requests imply main-thread progress in the pinned cooperative
client, not arbitrary application responsiveness or GPU completion.
"""
from collections import deque
from dataclasses import dataclass
from ui_intent import UIIntentGate, _number

POLICY_ID = 'cooperative-owned-foreground.v1'
EXCHANGE_MAX_S = .5
PROGRESS_MAX_S = 2.5
INVALIDATION_REASONS = frozenset(('intent_generation_changed','transport_intent_changed',
    'progress_intent_unavailable','progress_request_overlap','progress_arrival_gap',
    'progress_completion_invalid','progress_identity_or_intent_unavailable',
    'progress_exchange_timeout','progress_stale_or_generation_changed','progress_handler_failed',
    'progress_transport_unavailable','progress_stream_close_failed','progress_control_pending',
    'progress_request_refused','progress_request_timeout','progress_request_failed',
    'progress_projection_refused','progress_write_failed','progress_foreground_changed',
    'listener_start_failed','listener_listener_close_unconfirmed','listener_driver_cancelled',
    'listener_driver_failed','listener_cleanup_cancelled','listener_cleanup_failed',
    'listener_setup_failed','listener_setup_timeout','listener_accepted_close_unconfirmed',
    'listener_handler_failed','listener_stream_close_unconfirmed','listener_progress_publication_failed',
    'listener_closed','listener_refused','other'))


@dataclass(frozen=True)
class StatusTicket:
    sequence: int
    binding: object
    intent_revision: int
    progress_revision: int
    arrived: float


class CooperativeProgress:
    def __init__(self, gate, capability):
        if type(gate) is not UIIntentGate:
            raise TypeError('Exact owner UI intent gate required')
        gate._authorize(capability)
        if gate._progress is not None:
            raise ValueError('One cooperative observer per intent gate')
        self.gate, self._capability = gate, capability
        self.revision = self.sequence = self.consecutive = 0
        self.pending = self.completed = None
        self.reason = 'awaiting_status_progress'
        self.events = deque(maxlen=128)
        self.totals = {'attempts':0,'successful_exchanges':0,'successful_pairs':0,
            'max_observed_exchange_s':0.,'max_successful_exchange_s':0.,
            'max_observed_arrival_gap_s':0.,'max_observed_completed_age_s':0.}
        self.invalidations = {reason:0 for reason in sorted(INVALIDATION_REASONS)}
        gate._progress = self

    def _owner(self):
        self.gate._authorize(self._capability)

    def invalidate(self, reason):
        self._owner()
        # Diagnostic only: do not authorize with this unchecked clock read or
        # reenter gate._now() when that gate is already revoking a clock fault.
        try: observed = self.gate._clock()
        except Exception: observed = None
        self._record_elapsed(observed)
        if self.completed is not None and _number(observed) and observed >= self.completed['closed']:
            self.totals['max_observed_completed_age_s'] = max(
                self.totals['max_observed_completed_age_s'],observed-self.completed['closed'])
        self.invalidations[reason if reason in INVALIDATION_REASONS else 'other'] += 1
        self.revision += 1
        self.pending = self.completed = None
        self.consecutive = 0
        self.reason = reason
        self.events.append({'event': 'invalidated', 'revision': self.revision, 'reason': reason,
            'observed_at':observed if _number(observed) else None,
            'intent_revision':self.gate._revision})

    def _record_elapsed(self, now):
        if self.pending is not None and _number(now) and now >= self.pending.arrived:
            self.totals['max_observed_exchange_s'] = max(
                self.totals['max_observed_exchange_s'],now-self.pending.arrived)

    def _context(self):
        active = self.gate._active
        if active is None or active[0] != self.gate._binding:
            return None
        binding = active[0]
        if binding.session_id in self.gate._retired or binding.task_id in self.gate._terminal:
            return None
        return binding, self.gate._revision

    def begin(self, session):
        self._owner()
        now = self.gate._now()
        context = self._context()
        if now is None or context is None or context[0].session_id != session:
            self.invalidate('progress_intent_unavailable')
            return None
        if self.pending is not None:
            self.invalidate('progress_request_overlap')
        previous = self.completed
        if previous is not None and now >= previous['closed']:
            self.totals['max_observed_arrival_gap_s'] = max(
                self.totals['max_observed_arrival_gap_s'],now-previous['closed'])
        if previous is not None and not 0 <= now - previous['closed'] <= PROGRESS_MAX_S:
            self.invalidate('progress_arrival_gap')
        self.sequence += 1
        self.totals['attempts'] += 1
        ticket = StatusTicket(self.sequence, context[0], context[1], self.revision, now)
        self.pending = ticket
        return ticket

    def complete(self, ticket):
        """Trusted listener callback only, after exact handler/stream/socket join."""
        self._owner()
        now = self.gate._now()
        self._record_elapsed(now)
        if (type(ticket) is not StatusTicket or self.pending is not ticket
                or now is None or ticket.progress_revision != self.revision
                or self._context() != (ticket.binding, ticket.intent_revision)
                or not 0 <= now - ticket.arrived <= EXCHANGE_MAX_S):
            self.invalidate('progress_completion_invalid')
            return False
        previous = self.completed
        consecutive = (previous is not None and previous['sequence'] + 1 == ticket.sequence
            and previous['intent_revision'] == ticket.intent_revision
            and 0 <= ticket.arrived - previous['closed'] <= PROGRESS_MAX_S)
        self.consecutive = min(2, self.consecutive + 1) if consecutive else 1
        self.totals['successful_exchanges'] += 1
        self.totals['successful_pairs'] += int(self.consecutive == 2)
        self.totals['max_successful_exchange_s'] = max(
            self.totals['max_successful_exchange_s'],now-ticket.arrived)
        self.completed = {'sequence': ticket.sequence, 'intent_revision': ticket.intent_revision,
            'arrived': ticket.arrived, 'closed': now, 'elapsed_s': now-ticket.arrived}
        self.pending = None
        self.reason = 'progress_healthy' if self.consecutive == 2 else 'awaiting_following_status'
        self.events.append({'event': 'completed', **self.completed, 'consecutive': self.consecutive})
        return True

    def healthy(self, sample, now):
        self._owner()
        if not self.gate.matches(sample, now):
            self.invalidate('progress_identity_or_intent_unavailable')
            return False
        current = self.gate._now()
        if (current is None or not _number(now) or current < now
                or self.pending is not None and current-self.pending.arrived > EXCHANGE_MAX_S):
            self.invalidate('progress_exchange_timeout')
            return False
        if self.completed is None or self.consecutive < 2:
            return False
        if (self._context() != (self.gate._binding, self.completed['intent_revision'])
                or not 0 <= current-self.completed['closed'] <= PROGRESS_MAX_S):
            self.invalidate('progress_stale_or_generation_changed')
            return False
        return True

    def snapshot(self):
        self._owner()
        return {'policy_id': POLICY_ID, 'revision': self.revision, 'sequence': self.sequence,
            'bounds': {'exchange_max_s': EXCHANGE_MAX_S, 'next_arrival_max_s': PROGRESS_MAX_S,
                'completion_max_age_s': PROGRESS_MAX_S, 'required_consecutive': 2,
                'host_cpu_clear_fraction': .80, 'host_cpu_busy_fraction': .95,
                'activity_max_age_s': 1, 'memory_min_gib': 4, 'recovery_s': 5, 'busy_samples': 2},
            'consecutive': self.consecutive, 'reason': self.reason,
            'pending_sequence': None if self.pending is None else self.pending.sequence,
            'completed': None if self.completed is None else dict(self.completed),
            'totals':dict(self.totals),'invalidations':dict(self.invalidations),
            'scope':'Host lifetime totals; pairs never cross intent/progress generation; no UI/GPU latency claim',
            'events': list(self.events)}
