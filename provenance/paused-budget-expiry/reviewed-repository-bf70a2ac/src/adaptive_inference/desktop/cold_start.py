# SPDX-License-Identifier: Apache-2.0
"""Private cold-parking prototype; no host, demand poller or automatic dispatch.

Reuse the canonical NativeOwnerAdapter's serialization, exact owner identities,
startup failure handle and release proof. See README for the pinned dependency.
"""
import asyncio
from copy import deepcopy
import os

from adaptive_inference.desktop.native_owner_adapter import NativeOwnerAdapter, OwnerPackage, identity


class ColdOwnerPackage(OwnerPackage):
    def owner_idle(self):
        """Reuse the same owner-lock probe as OwnerPackage.start_owner."""
        if self.module is None:
            self.verify()
        token=self.module.lock(self.root/'state/owner.lock')
        self.module.unlock(token)
        return True


class ColdStartAdapter(NativeOwnerAdapter):
    def __init__(self, package=None, *, manifest_sha256=None, provenance_sha256=None,
                 max_runtime_seconds=900, job, _driver=None):
        driver=_driver if _driver is not None else ColdOwnerPackage(
            package,manifest_sha256,provenance_sha256)
        super().__init__(_driver=driver,max_runtime_seconds=max_runtime_seconds)
        self.job=job
        self._cold_prepared=False
        self._cold_closed=False
        self._cold_closing=False
        self._cold_close_work=None
        self.started_owner=False
        self.launch_intent=None
        self._cold_start_error=None
        self.parked_observation=None

    def _outer_job_empty(self):
        members=self.job.active_process_ids()
        if type(members) is not set or members!={os.getpid()}:
            raise RuntimeError('Containing job is not empty apart from this host')

    def _stopped_identity(self, state):
        if (type(state) is not dict or state.get('running') is not False
                or state.get('state') not in ('stopped','failed')
                or state.get('ready') is True or state.get('loaded') is True):
            raise RuntimeError('Cold parking refuses a live or uncertain backend')
        if any(state.get(key) is not None for key in ('owner_id','owner','run')):
            previous=identity(state)
            if (state.get('cleanup_confirmed') is not True
                    or type(state.get('processes')) is not dict
                    or state['processes'].get('active')!=[]):
                raise RuntimeError('Previous owner has no complete cleanup receipt')
        else:
            previous=None
            if ('processes' in state and (type(state['processes']) is not dict
                    or state['processes'].get('active')!=[])):
                raise RuntimeError('Ownerless status contains unknown process state')
        if self._expected is not None and previous!=self._expected:
            raise RuntimeError('Stopped owner changed outside this adapter')
        return previous

    def _prepare_parked(self):
        if self._cold_closed or self._cold_closing or self.started_owner:
            raise RuntimeError('Cold initialization is only valid before the first launch')
        if self._startup_failure is not None:
            raise self._startup_failure
        if self._observed_live:
            raise RuntimeError('Cold initialization cannot adopt a previously observed live owner')
        self._cold_prepared=False
        if self._barrier is None:
            self._barrier=self.driver.lock_start()
        self.driver.verify()
        before=self.driver.status()
        previous=self._stopped_identity(before)
        if self.driver.owner_idle() is not True:
            raise RuntimeError('Native owner lock is not independently idle')
        if self.driver.port_free(18098) is not True:
            raise RuntimeError('Backend port is not independently free')
        self._outer_job_empty()
        after=self.driver.status()
        if self._stopped_identity(after)!=previous:
            raise RuntimeError('Owner identity changed during cold parking')
        self._expected=deepcopy(previous)
        self._cold_prepared=True
        self.parked_observation={'state':'parked','running':False,'ready':False,'loaded':False,
            'owner_id':None,'previous_owner_id':None if previous is None else previous['owner_id'],
            'startup_barrier_held':True,'owner_lock_observed_idle':True,'backend_port_free':True,
            'containing_job_empty':True,'native_launch_attempted':False,'release':None,
            'scope':'Cooperating package and containing job observed parked; no model release, capacity reservation or OS-wide process claim.'}
        return deepcopy(self.parked_observation)

    async def prepare_parked(self):
        return await self._call(self._prepare_parked)

    def _status(self):
        if self._cold_start_error is not None:
            raise self._cold_start_error
        if not self.started_owner:
            state=self.driver.status()
            self._stopped_identity(state)
            return state  # Never let an initial status read adopt a live owner.
        return super()._status()

    def _start(self):
        if self._cold_closed or self._cold_closing or not self._cold_prepared:
            raise RuntimeError('Verified cold initialization is required before deferred start')
        if self._startup_failure is not None:
            raise self._startup_failure
        if self._cold_start_error is not None:
            raise self._cold_start_error
        # Intent is set inside the same serialized operation, before the parent
        # can invoke Popen. Cancellation cannot erase this cleanup obligation.
        self.started_owner=True
        self.launch_intent={'attempt':1 if self.launch_intent is None else self.launch_intent['attempt']+1,
            'state':'starting','owner_id':None,'normal_release_confirmed':False}
        try:
            state=super()._start()
        except BaseException as exc:
            self._cold_start_error=exc
            # Even a generic error can follow a launch. An earlier owner's
            # successful release says nothing about this new attempt.
            self._released=None
            self.launch_intent['state']='failed_or_unconfirmed'
            raise
        self.launch_intent.update(state='ready',owner_id=state['owner_id'])
        return state

    async def close_parked(self):
        """Close only an observed quiescent adapter; never stop active work here.

        The host must close admission/drain and call inherited stop first for a
        loaded owner. Failed startup uses its existing exact-handle diagnostic.
        """
        # Retain and shield the whole two-stage close, not only its first
        # serialized check. A canceled caller can retrieve the same completed
        # receipt; a failed close may recheck evidence while starts stay fenced.
        work=self._cold_close_work
        if work is None or (work.done() and (work.cancelled() or work.exception() is not None)):
            work=asyncio.create_task(self._finish_parked_close())
            self._cold_close_work=work
        cancelled=None
        while not work.done():
            try:
                await asyncio.shield(work)
            except asyncio.CancelledError as exc:
                cancelled=exc
            except Exception:
                break  # Retrieve the retained operation's exact failure below.
        try:
            return deepcopy(work.result())
        finally:
            if cancelled is not None:
                raise cancelled

    async def _finish_parked_close(self):
        def check():
            if self._barrier is None:
                self._barrier=self.driver.lock_start()
            if self._startup_failure is not None:
                failure=self._failed_start_status()
                if ((failure['process_created'] and not failure['owner_exit_confirmed'])
                        or failure.get('process_observation_error') or failure['port_free'] is not True):
                    raise RuntimeError('Failed startup remains unresolved') from self._startup_failure
                outcome='failed_start_cleanup'
            else:
                if self._cold_start_error is not None:
                    raise RuntimeError('Deferred startup remains unresolved') from self._cold_start_error
                state=self.driver.status()
                self._stopped_identity(state)
                if self.started_owner:
                    if (self._released is None or self.launch_intent['state']!='ready'
                            or self._released.get('owner_id')!=self.launch_intent['owner_id']
                            or self._expected['owner_id']!=self.launch_intent['owner_id']):
                        raise RuntimeError('Current deferred launch has no verified normal release')
                if self.driver.owner_idle() is not True or self.driver.port_free(18098) is not True:
                    raise RuntimeError('Parked native ownership is not free')
                outcome='released_owner' if self.started_owner else 'never_launched'
            self._outer_job_empty()
            # Fence any concurrent deferred start before awaiting parent close.
            self._cold_closing=True
            return {'outcome':outcome,'native_launch_attempted':self.started_owner,
                    'attempt':None if self.launch_intent is None else self.launch_intent['attempt'],
                    'normal_release_confirmed':self._released is not None,
                    'release':deepcopy(self._released),'owned_children_exited':True}
        result=await self._call(check)
        await super().close(release_parked=True)
        self._cold_closed=True
        if self.launch_intent is not None:
            self.launch_intent['normal_release_confirmed']=result['normal_release_confirmed']
        return result
