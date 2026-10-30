# SPDX-License-Identifier: Apache-2.0
"""Pinned Hermes activity/watchdog components; no full agent or model launch.

Bootstrap reuses ../hermes_pause_dispatch/check_sdk.py. Controlled clocks and
ParkingReleaseLock adapt the MIT upstream watchdog tests pinned in sdk-references.json.
"""
from contextlib import ExitStack
from copy import deepcopy
from importlib import metadata
from pathlib import Path
from types import ModuleType, SimpleNamespace
import argparse
import hashlib
import json
import os
import sys
import threading
import time
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--profile', type=Path, required=True)
parser.add_argument('--mode', choices=('source', 'installed'), required=True)
parser.add_argument('--installed-identity', type=Path)
options = parser.parse_args()
if (options.mode == 'installed') != (options.installed_identity is not None):
    parser.error('Installed mode requires --installed-identity; source mode does not accept it')
out = options.output.resolve()
out.mkdir(exist_ok=False)
os.environ.update(HERMES_HOME=str(out/'home'), LITELLM_LOCAL_MODEL_COST_MAP='True',
                  PYTHONDONTWRITEBYTECODE='1')
os.environ.pop('HERMES_KANBAN_TASK', None)

def no_external_work(event, args):
    if event in ('socket.connect', 'socket.bind', 'subprocess.Popen', 'os.system', 'os.startfile'):
        raise RuntimeError('Component check forbids external work: '+event)

sys.addaudithook(no_external_work)
sys.path.insert(0, str(REPO/'tests'))
if options.mode == 'source':
    sys.path.insert(0, str(REPO/'src'))
from adaptive_inference.desktop.profile import WindowsProfile
from adaptive_inference.desktop.installation import (
    package_identity, verify_interpreter, verify_sdk, verify_sdk_imports,
)
profile = WindowsProfile.load(options.profile)
verify_interpreter(profile.worker_python, profile.worker_python_sha256, current=True)
SDK = profile.hermes_source.resolve(strict=True)
references_path = HERE/'sdk-references.json'
references = json.loads(references_path.read_text(encoding='utf-8'))
verify_sdk(SDK)
for relative, expected in references['files'].items():
    if hashlib.sha256((SDK/relative).read_bytes()).hexdigest() != expected:
        raise RuntimeError('Changed SDK component reference: '+relative)
sys.path[:0] = [str(SDK), str(profile.hermes_site_packages)]
from adaptive_inference.desktop.hermes import pause_activity, recovery as rec
from agent import activity_tracking, session_activity, turn_liveness, turn_facade_lease, interrupt_control
from tools import interrupt
import test_admission_wait_expiry as fixture

identity = (package_identity(json.loads(options.installed_identity.read_text(encoding='utf-8')))
            if options.installed_identity is not None else None)
runtime_root = Path(rec.__file__).resolve().parents[2]
if identity is None:
    assert runtime_root == (REPO/'src/adaptive_inference').resolve()
else:
    assert runtime_root == (Path(sys.base_prefix)/'Lib/site-packages/adaptive_inference').resolve()
    assert str((REPO/'src').resolve()) not in sys.path

def check_imports():
    verify_sdk_imports(SDK)
    if 'run_agent' in sys.modules or 'agent.periodic_scheduler' in sys.modules:
        raise RuntimeError('Full agent or periodic scheduler was imported')
    loaded = {}
    for name, module in tuple(sys.modules.items()):
        source = getattr(module, '__file__', None)
        if source is None:
            continue
        path = Path(source).resolve()
        if path.is_relative_to(SDK):
            relative = path.relative_to(SDK).as_posix()
            if relative not in references['files']:
                raise RuntimeError('Unreviewed SDK import: '+relative)
            if hashlib.sha256(path.read_bytes()).hexdigest() != references['files'][relative]:
                raise RuntimeError('SDK import changed: '+relative)
            loaded[name] = relative
        elif name in references['modules']:
            raise RuntimeError('SDK component resolved outside pinned checkout: '+name)
        if name == 'adaptive_inference' or name.startswith('adaptive_inference.'):
            if not path.is_relative_to(runtime_root):
                raise RuntimeError('Mixed canonical import: '+name)
    for name, relative in references['modules'].items():
        module = sys.modules.get(name)
        if module is None or Path(module.__file__).resolve() != SDK/relative:
            raise RuntimeError('Expected component import is unavailable: '+name)
    return loaded

check_imports()


class ComponentAgent(activity_tracking.ActivityTrackingMixin, interrupt_control.InterruptControlMixin):
    """Only component state; no AIAgent constructor, client, tools or children."""
    def __init__(self, database):
        self.session_id, self._session_db = 'native', database
        self._active_session_turn_lease_holder = 'component-holder'
        self._interrupt_requested = self._turn_user_intervened = False
        self._interrupt_message = self._tool_interrupt_reason = None
        self._hard_interrupt_requested = threading.Event()
        self._execution_thread_id = None
        self._interrupt_thread_signal_pending = False
        self._active_children_lock = threading.Lock()
        self._active_children = set()
        self._pending_redirect_lock = threading.RLock()
        self._pending_redirect = None
        self.quiet_mode = True
        self.warnings = []

    def _emit_warning(self, value):
        self.warnings.append(value)


class ParkingReleaseLock:
    """MIT upstream test pattern: park AFTER releasing the selected lock edge."""
    def __init__(self, inner):
        self._inner = inner
        self.park_on_release = None
        self.release_count = 0
        self.parked, self.release_park = threading.Event(), threading.Event()

    def __enter__(self):
        return self._inner.__enter__()

    def __exit__(self, *exc_info):
        result = self._inner.__exit__(*exc_info)
        self.release_count += 1
        if self.park_on_release is not None and self.release_count == self.park_on_release:
            self.parked.set()
            if not self.release_park.wait(5):
                raise TimeoutError('Reserved-claim component race was not released')
        return result


PROJECTIONS = {}


class SDKAdmissionActivity(unittest.TestCase):
    release = fixture.WaitSealTests.release

    def setUp(self):
        fixture.WaitSealTests.setUp(self)
        self.now = 0.0
        self.controls.deadline = 900.0
        state = deepcopy(self.owned.checkpoint.state)
        state['deadline_monotonic'] = 900.0
        self.owned.save_checkpoint(state, expected_revision=self.owned.checkpoint.revision)
        self.before = deepcopy(self.owned.checkpoint.state)
        self.mailbox_before = self.box.snapshot()
        self.clock = SimpleNamespace(wall=1000.0, mono=1000.0)
        timer = SimpleNamespace(time=lambda: self.clock.wall, monotonic=lambda: self.clock.mono)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for module in (activity_tracking, session_activity, turn_liveness, turn_facade_lease):
            self.stack.enter_context(mock.patch.object(module, 'time', timer))
        self.agent = self.controller.agent = ComponentAgent(self.db)
        self.assertFalse(callable(getattr(self.db, 'touch_session_activity', None)))
        self.lease_reads = []
        def lease_expiry(session, holder):
            self.assertEqual((session, holder), ('native', 'component-holder'))
            self.lease_reads.append(self.clock.wall)
            return 3000.0
        # The real writer/watchdog/abort components use a reduced SQLite fixture;
        # this explicit live-row getter does not claim SessionDB renewal coverage.
        self.db.session_turn_lease_expires_at = lease_expiry
        self.guard = pause_activity.PauseActivity(self.controller, wall_clock=timer.time,
                                                  thread_interrupted=interrupt.is_interrupted)
        self.controls.wait_activity = self.guard
        self.lease = turn_facade_lease.DurableTurnLease(
            self.agent, self.db, 'native', 'component-holder', expires_at=3000.0)
        with self.lease._lock:
            self.lease.turn_active = True
        self.addCleanup(self.lease.stop_refresher)
        self.watchdog = turn_liveness.TurnLivenessWatchdog(
            self.agent, session_id='native', timeout_s=600, poll_s=15,
            stop_event=self.lease.stop, activity_lock=self.agent._liveness_activity_lock(),
            is_turn_active=self.lease.is_turn_active, commit_abort=self.lease.commit_liveness_abort,
            deactivate_turn=self.lease.stop_refresher)
        self.stack.enter_context(mock.patch.object(self.watchdog, '_dump_turn_thread_stack', return_value=None))
        self.metrics = []
        metrics_module = ModuleType('hermes_cli.observability.shared_metrics_process')
        metrics_module.record_watchdog_turn_abort = lambda agent: self.metrics.append(agent is self.agent)
        self.stack.enter_context(mock.patch.dict(sys.modules, {
            'hermes_cli.observability.shared_metrics_process': metrics_module}))
        # Check case-local imports before patch.dict restores the module table.
        self.addCleanup(check_imports)

    def advance(self, instant):
        self.now = float(instant)
        self.clock.wall = self.clock.mono = 1000.0 + instant

    def preserved(self):
        self.assertEqual(self.owned.checkpoint.state, self.before)
        self.assertEqual(self.box.snapshot(), self.mailbox_before)
        self.assertEqual(rec.native_history(self.db, 'native'), self.before['native_history'])
        self.assertIsNone(self.owned.checkpoint.operation)
        self.assertEqual(self.controls.deadline, 900.0)
        self.assertIsNone(self.controller.provider)
        self.assertEqual(self.before['tools'], [])

    def record(self, **details):
        PROJECTIONS[self._testMethodName] = {
            'activity_generation': self.agent._turn_liveness_activity_generation,
            'activity_timestamp': self.agent._last_activity_ts,
            'guard_stamps': self.guard.stamps, 'deadline': self.controls.deadline,
            'turn_active': self.lease.is_turn_active(), 'lease_stop': self.lease.stop.is_set(),
            'interrupted': self.agent._interrupt_requested,
            'hard_interrupt': self.agent._hard_interrupt_requested.is_set(),
            'pending_sha256': rec.digest(self.owned.checkpoint.state['pending_request']),
            'native_sha256': rec.digest(self.before['native_history']), **details}

    def test_verified_wait_survives_six_hundred_and_original_deadline_stops_stamps(self):
        stamps = []
        for instant in range(0, 900, 15):
            self.advance(instant)
            self.controller.control_safe_point()
            stamps.append(self.agent._last_activity_ts)
            self.assertIsNone(self.watchdog._tick())
        for instant in (900, 901):
            self.advance(instant)
            with self.assertRaises(rec.ControlStop) as caught:
                self.controller.control_safe_point()
            self.assertEqual((caught.exception.control_state, caught.exception.reason),
                             ('active', 'control_wait_deadline'))
            self.assertIsNone(self.watchdog._tick())
        self.assertEqual(stamps, [1000.0+i for i in range(0, 900, 15)])
        self.assertEqual((self.guard.stamps, self.agent._turn_liveness_activity_generation), (60, 60))
        self.assertEqual(self.agent._last_activity_ts, 1885.0)
        self.assertEqual(self.agent._last_activity_desc, 'waiting for adaptive admission')
        self.assertTrue(self.lease.is_turn_active())
        self.assertFalse(self.agent._interrupt_requested)
        self.assertEqual(self.metrics, [])
        self.preserved()
        self.record(last_activity_execution=885, checked_through=901, no_stamp_at_or_after_deadline=True)

    def test_silent_turn_commits_real_abort_and_guard_cannot_revive_it(self):
        self.agent._touch_activity('component turn start')
        for instant in range(15, 600, 15):
            self.advance(instant)
            self.assertIsNone(self.watchdog._tick())
        self.advance(600)
        self.assertIs(self.watchdog._tick(), False)
        self.assertTrue(self.agent._interrupt_requested)
        self.assertTrue(self.agent._turn_user_intervened)
        self.assertTrue(self.agent._hard_interrupt_requested.is_set())
        self.assertEqual(self.agent._tool_interrupt_reason, 'turn liveness watchdog')
        self.assertFalse(self.lease.is_turn_active())
        self.assertTrue(self.lease.stop.is_set())
        self.assertEqual(self.metrics, [True])
        self.assertEqual(len(self.agent.warnings), 2)
        with self.assertRaises(rec.RecoveryStop):
            self.controller.control_safe_point()
        self.assertIsNotNone(self.guard.fault)
        self.assertEqual(self.guard.stamps, 0)
        self.assertEqual(self.agent._turn_liveness_activity_generation, 1)
        self.preserved()
        self.record(abort_at_execution=600, metrics_count=1, revived=False)

    def test_verified_owner_stamp_invalidates_reserved_abort_claim(self):
        self.controller.control_safe_point()
        lock = ParkingReleaseLock(self.agent._liveness_activity_lock())
        self.agent._turn_liveness_activity_lock = lock
        self.watchdog._activity_lock = lock
        # Sampling release, lease revalidation release, then interrupt reservation.
        lock.park_on_release = 3
        self.advance(600)
        outcomes, errors = [], []
        def abort_tick():
            try:
                outcomes.append(self.watchdog._tick())
            except BaseException as exc:
                errors.append(type(exc).__name__+': '+str(exc))
        contender = threading.Thread(target=abort_tick, name='component-reserved-abort')
        contender.start()
        try:
            self.assertTrue(lock.parked.wait(5), 'Abort did not reach its reserved-claim boundary')
            self.assertEqual(self.agent._turn_liveness_abort_claim, 1)
            self.assertFalse(self.agent._interrupt_requested)
            self.controller.control_safe_point()
            self.assertEqual(self.agent._turn_liveness_activity_generation, 2)
            self.assertIsNone(self.agent._turn_liveness_abort_claim)
        finally:
            lock.release_park.set()
            contender.join(5)
        self.assertFalse(contender.is_alive(), 'Exact abort contender did not join')
        self.assertEqual(errors, [])
        self.assertEqual(outcomes, [None])
        self.assertFalse(self.agent._interrupt_requested)
        self.assertFalse(self.agent._hard_interrupt_requested.is_set())
        self.assertTrue(self.lease.is_turn_active())
        self.assertFalse(self.lease.stop.is_set())
        self.assertEqual(self.metrics, [])
        self.assertIsNone(self.guard.fault)
        self.preserved()
        self.record(reserved_claim=1, declined_abort=True, contender_joined=True)


sources = [Path(__file__).resolve(), HERE/'README.md', references_path,
           options.profile.resolve(strict=True), *(SDK/name for name in references['files']),
           *runtime_root.rglob('*.py'), *(REPO/'tests'/name for name in references['fixture_files'])]
if options.installed_identity is not None:
    sources.append(options.installed_identity.resolve(strict=True))

def pins():
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}

before = pins()
started = time.monotonic()
with (out/'tests.log').open('x', encoding='utf-8') as stream:
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(SDKAdmissionActivity))
after = pins()
loaded = check_imports()
verify_sdk(SDK)
if identity is not None:
    package_identity(identity)
external_modules = {}
for name, module in tuple(sys.modules.items()):
    if name == 'jiter' or name.startswith('jiter.') or name == 'ruamel' or name.startswith('ruamel.'):
        source = getattr(module, '__file__', None)
        if source:
            path = Path(source).resolve()
            external_modules[name] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
versions = {}
for name in ('jiter', 'ruamel.yaml'):
    try:
        versions[name] = metadata.version(name)
    except metadata.PackageNotFoundError:
        versions[name] = None
receipt = {
    'passed': result.wasSuccessful() and before == after and len(PROJECTIONS) == 3,
    'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
    'skipped': len(result.skipped), 'elapsed_s': time.monotonic()-started,
    'source_before': before, 'source_after': after, 'source_unchanged': before == after,
    'sdk_loaded_modules': loaded, 'external_modules': external_modules, 'external_versions': versions,
    'installed_mode': identity is not None, 'package_identity': identity,
    'python': sys.version, 'executable': sys.executable, 'cases': PROJECTIONS,
    'log_sha256': hashlib.sha256((out/'tests.log').read_bytes()).hexdigest(),
    'scope': 'Actual pinned activity writer, watchdog tick, awake-idle meter, durable-lease abort commit and interrupt publication with controlled clocks and reduced real SQLite. No AIAgent, scheduler, network, model, UI, native engine, durable SessionDB heartbeat, actual lease renewal, hardware elapsed-time or full recovery claim.',
}
path = out/'tests.private.json'
with path.open('x', encoding='utf-8', newline='\n') as stream:
    stream.write(json.dumps(receipt, indent=2)+'\n')
print(json.dumps({key: receipt[key] for key in ('passed', 'tests', 'failures', 'errors', 'elapsed_s', 'installed_mode')}))
print(hashlib.sha256(path.read_bytes()).hexdigest())
raise SystemExit(0 if receipt['passed'] else 1)
