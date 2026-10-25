# SPDX-License-Identifier: Apache-2.0
"""Tk owner-thread startup orchestration, with explicit injected boundaries."""
import threading
import time

from control_client import ClientController, NetworkWorker
from startup_pipe import ChildHandshake


class GUISession:
    def __init__(self, root, view, bootstrap, marker, stdin, stdout, exchange, *,
                 handshake_factory=ChildHandshake, worker_factory=NetworkWorker,
                 controller_factory=ClientController, clock=time.monotonic, startup_timeout_s=10):
        if type(startup_timeout_s) not in (int, float) or not 0 < startup_timeout_s <= 30:
            raise ValueError('Bounded startup observation deadline required')
        self.root, self.view, self.bootstrap, self.marker = root, view, bootstrap, marker
        self.stdin, self.stdout, self.exchange = stdin, stdout, exchange
        self.handshake_factory, self.worker_factory, self.controller_factory = handshake_factory, worker_factory, controller_factory
        self.clock, self.startup_timeout_s = clock, startup_timeout_s
        self.owner = threading.current_thread()
        self.handshake = self.worker = self.controller = None
        self.closing = self.closed = False
        self._activation_failed = False
        self.faults = set()
        self.deadline = None

    def _owner(self):
        if threading.current_thread() is not self.owner:
            raise RuntimeError('GUI startup belongs to its Tk thread')

    def start(self):
        self._owner()
        if self.deadline is not None:
            raise RuntimeError('GUI session cannot restart')
        self.deadline = self.clock() + self.startup_timeout_s
        try:
            self.marker.install()
            self.handshake = self.handshake_factory(self.bootstrap, self.marker.hwnd, self.stdin, self.stdout)
            self.handshake.start()
            self.root.protocol('WM_DELETE_WINDOW', self.close)
            self.root.after(20, self.tick)
        except BaseException:
            self.faults.add('gui_startup_failed')
            self.close()
            raise

    def close(self):
        self._owner()
        self.closing = True
        if self.controller is not None:
            try:
                self.controller.close()
            except BaseException:
                self.faults.add('client_close_unconfirmed')
                if self.worker is not None:
                    self.worker.close()
        else:
            try:
                if not self.marker.remove():
                    self.faults.add('startup_marker_removal_unconfirmed')
            except BaseException:
                self.faults.add('startup_marker_removal_failed')
            if self.worker is not None:
                self.worker.close()

    def tick(self):
        self._owner()
        joined = self.handshake is None or self.handshake.joined()
        if self.controller is None and not self.closing:
            if self.clock() >= self.deadline:
                self.faults.add('startup_deadline_unresolved')
                self.close()
            elif joined:
                if self.handshake is None or not self.handshake.accepted or self.handshake.error:
                    self.faults.add('startup_ack_unconfirmed')
                    self.close()
                else:
                    # All GUI/worker/controller activation happens after parent
                    # retained verification, session binding and ACK+EOF.
                    try:
                        self.worker = self.worker_factory(self.exchange)
                        self.controller = self.controller_factory(self.bootstrap, self.worker, self.marker, self.view,
                            close_on_stop_recorded=True)
                        self.view.attach(self.controller)
                        self.controller.start()
                    except BaseException:
                        # Tk reports callback failures without unwinding mainloop.
                        # Preserve a partial worker/controller and finish cleanup
                        # here even if view.attach never installed its callbacks.
                        self.faults.add('client_activation_failed')
                        self._activation_failed = True
                        self.close()
        cleanup_here = self.controller is None or self._activation_failed
        worker_joined = True
        if self.closing and cleanup_here and self.worker is not None:
            for _ in range(3):
                self.worker.take()
            worker_joined = self.worker.joined()
        if self.closing and cleanup_here and joined and worker_joined and not self.closed:
            # Failed startup may destroy its presentation while retaining faults;
            # it never claims clean native or worker shutdown from that action.
            try:
                self.view.destroy()
                self.closed = True
            except BaseException:
                self.faults.add('startup_window_destroy_unconfirmed')
        if not self.closed and cleanup_here:
            self.root.after(20, self.tick)

    def after_mainloop(self):
        """Actual unexpected root destruction still owes both child threads a join."""
        self._owner()
        self.close()
        while self.handshake is not None and not self.handshake.joined():
            # The host owns the other pipe endpoint and its timeout fences it.
            # No claim of bounded completion if an injected/OS I/O stays stuck.
            time.sleep(.01)
        if self.worker is not None:
            self.worker.close()
            while not self.worker.joined():
                self.worker.take()
                time.sleep(.01)
        if not self.marker.destroyed:
            try:
                self.view.destroy()
            except BaseException:
                self.faults.add('final_window_destroy_unconfirmed')
        if self.controller is not None and self.controller.cleanup_error is not None:
            self.faults.add('client_cleanup_unconfirmed')
        return not self.faults and not self.marker.faults
