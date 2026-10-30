# SPDX-License-Identifier: Apache-2.0
"""Report only serialized logical-owner Pause waits to the pinned Hermes watchdog.

This is activity, not model/tool progress. No timer thread or lease renewal is
introduced. A blocked/failed owner or lease read cannot generate a heartbeat.
"""
import math
import os
import threading
import time
from contextlib import contextmanager

from adaptive_inference.desktop.hermes.recovery import RecoveryStop

WAIT_ACTIVITY_SECONDS = 15.0
ABORT_REASONS = frozenset(('turn liveness watchdog', 'session turn lease lost'))


def reject_aborted_agent(agent):
    if agent is None:
        return
    event = getattr(agent, '_hard_interrupt_requested', None)
    if (getattr(agent, '_interrupt_requested', False)
            or getattr(agent, '_turn_user_intervened', False)
            or getattr(agent, '_tool_interrupt_reason', None) in ABORT_REASONS
            or event is not None and event.is_set()):
        raise RecoveryStop('Hermes turn was interrupted; Pause cannot renew its authority')


class PauseActivity:
    def __init__(self, recovery, *, wall_clock=time.time, thread_interrupted=None):
        self.recovery = recovery
        self.wall_clock = wall_clock
        self.lock = recovery.lock
        self.owned = recovery.owned
        self.epoch = self.owned.checkpoint.owner_epoch
        if thread_interrupted is not None and not callable(thread_interrupted):
            raise TypeError('Explicit SDK thread interruption reader required')
        self.thread_interrupted = thread_interrupted
        self.revoked = threading.Event()
        self.holder = None
        self.session = None
        self.last_stamp = None
        self.fault = None
        self.stamps = 0
        self.finished = False

    def finish_turn(self, outcome):
        with self.lock:
            self.check_final(self.recovery.agent)
            if (type(outcome) is not dict or outcome.get('completed') is not True
                    or outcome.get('failed', False) is not False or outcome.get('interrupted', False) is not False
                    or self.recovery.agent is None
                    or getattr(self.recovery.agent, '_active_session_turn_lease_holder', None) is not None):
                raise RecoveryStop('SDK turn did not return a verified completed result after lease release')
            self.finished = True

    def check_final(self, agent):
        with self.lock:
            try:
                self._health(agent)
            except BaseException as exc:
                if self.fault is None:
                    self.fault = 'Paused SDK authority check failed: '+type(exc).__name__
                raise

    def _identity(self):
        owned = self.owned
        if (self.recovery.lock is not self.lock or self.recovery.owned is not owned
                or owned._closed or owned._pid != os.getpid() or not owned._lock.held
                or owned._epoch != self.epoch or owned.checkpoint.owner_epoch != self.epoch):
            raise RecoveryStop('Paused SDK check lost its exact logical task ownership')

    def _health(self, agent, *, closing=False):
        self._identity()
        if self.revoked.is_set() and not closing:
            raise RecoveryStop('Paused SDK authority was revoked for cleanup')
        if self.fault is not None:
            raise RecoveryStop(self.fault)
        if agent is not self.recovery.agent:
            raise RecoveryStop('Paused SDK agent identity changed')
        reject_aborted_agent(agent)
        if agent is not None:
            if self.thread_interrupted is None or self.thread_interrupted() is not False:
                raise RecoveryStop('SDK tool worker was interrupted or its interruption state is unknown')

    def revoke(self):
        # Also callable while a blocked SDK callback owns the Recovery RLock.
        # A returning callback must recheck this latch before activity/dispatch.
        self.revoked.set()

    @contextmanager
    def cleanup_scope(self, agent, *, verify):
        self.revoke()
        if self.recovery.lock is not self.lock or not self.lock.acquire(blocking=False):
            raise RecoveryStop('SDK callback still owns recovery; cleanup is unconfirmed')
        try:
            if verify:
                self._health(agent, closing=True)
            yield
        finally:
            self.lock.release()

    def __call__(self, owned, pause_observation=None):
        with self.lock:
            try:
                self._check(owned, pause_observation)
            except BaseException as exc:
                if self.fault is None:
                    self.fault = 'Paused SDK authority check failed: '+type(exc).__name__
                raise

    def _check(self, owned, pause_observation):
        recovery = self.recovery
        if (owned is not self.owned
                or getattr(recovery, '_control_thread', None) is not threading.current_thread()):
            raise RecoveryStop('Paused SDK check requires its active serialized control boundary')
        self.check_final(recovery.agent)
        agent = recovery.agent
        if agent is None:
            return  # The initial paused bootstrap has no SDK turn yet.
        holder = getattr(agent, '_active_session_turn_lease_holder', None)
        if self.finished:
            if holder is not None:
                raise RecoveryStop('SDK lease reappeared after verified turn completion')
            return  # The original Recovery.finish safe point may still apply user controls.
        session = getattr(agent, 'session_id', None)
        if (type(holder) is not str or not holder or session != owned.checkpoint.state['session_id']
                or getattr(agent, '_session_db', None) is not recovery.db):
            raise RecoveryStop('Paused SDK turn identity is unavailable')
        if self.holder is None:
            self.holder, self.session = holder, session
        if (holder, session) != (self.holder, self.session):
            raise RecoveryStop('Paused SDK turn owner changed')
        expiry = recovery.db.session_turn_lease_expires_at(session, holder)
        now = self.wall_clock()  # After the read; never use a stale pre-I/O time.
        if (type(expiry) not in (int, float) or not math.isfinite(expiry)
                or type(now) not in (int, float) or not math.isfinite(now) or expiry <= now):
            raise RecoveryStop('Paused SDK turn lease is missing or expired')
        self._health(agent)
        controls = recovery.controls
        instant = controls.clock()
        if (pause_observation is not None and instant < controls.deadline
                and (self.last_stamp is None or instant-self.last_stamp >= WAIT_ACTIVITY_SECONDS)):
            # Controls obtains this exact observation only after its coherent
            # safe owner/prefix read. Do not stamp a poll, I/O attempt or thread.
            if controls.paused_expiry_observation != pause_observation:
                raise RecoveryStop('Paused SDK activity lacks its exact safe observation')
            agent._touch_activity('waiting at acknowledged adaptive Pause')
            self._health(agent)  # A committed interrupt/revocation cannot be erased by a touch.
            self.last_stamp = instant
            self.stamps += 1
