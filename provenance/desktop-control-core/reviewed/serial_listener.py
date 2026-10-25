# SPDX-License-Identifier: Apache-2.0
"""One serial loopback listener; closing it does not request host Stop."""
import asyncio
import math
import socket
import threading

from control_transport import ControlTransport


def duration(value, maximum):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= maximum:
        raise ValueError('A finite bounded duration is required')
    return value


class SerialListener:
    """Owner-loop adapter. A close timeout never cancels retained operations.

    socket_factory/open_stream are explicit test seams. Production uses standard
    nonblocking AF_INET sockets and open_connection(sock=...), no private asyncio
    accept APIs. Hold this object and the loop until resources_closed is true.
    """
    def __init__(self, transport, *, poll_interval=.05, setup_timeout=2,
                 socket_factory=None, open_stream=asyncio.open_connection):
        if type(transport) is not ControlTransport:
            raise TypeError('The unchanged ControlTransport is required')
        transport.lifecycle()  # Also checks the transport's actual owner loop.
        self.transport = transport
        self._loop, self._thread = asyncio.get_running_loop(), threading.current_thread()
        self.poll_interval = duration(poll_interval, .25)
        self.setup_timeout = duration(setup_timeout, 30)
        self._factory = socket_factory or (lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM))
        self._open = open_stream
        self._socket = self._driver = self._close_task = self._record = None
        self._started = self._closing = self._listener_close_attempted = False
        self._listener_closed = False
        self._endpoint = None
        self._faults, self._exceptions = set(), {}
        self.accepted = self.refused = 0

    def _owner(self):
        if threading.current_thread() is not self._thread or asyncio.get_running_loop() is not self._loop:
            raise PermissionError('Listener belongs to its host loop and thread')

    def _fault(self, code, error=None):
        self._faults.add(code)
        self.transport.invalidate_progress('listener_' + code)
        if error is not None:
            self._exceptions.setdefault(code, error)  # Bounded, private diagnostic.

    @property
    def endpoint(self):
        self._owner()
        return self._endpoint

    def start(self):
        """Bind and retain the driver before returning; never creates a host."""
        self._owner()
        if self._started or self._closing:
            raise RuntimeError('Listener cannot be restarted')
        self._started = True
        try:
            self._socket = self._factory()
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            self._socket.setblocking(False)
            self._socket.bind(('127.0.0.1', 0))
            self._socket.listen(1)
            self._endpoint = self._socket.getsockname()
            if (type(self._endpoint) is not tuple or len(self._endpoint) != 2
                    or self._endpoint[0] != '127.0.0.1'
                    or type(self._endpoint[1]) is not int or not 1 <= self._endpoint[1] <= 65535):
                raise RuntimeError('Unexpected listener endpoint')
            self._driver = self._loop.create_task(self._drive())
            self._driver.add_done_callback(self._driver_done)
            return self._endpoint
        except BaseException as error:
            self._fault('start_failed', error)
            self.close()
            raise

    def _fence(self):
        self._closing = True
        self.transport.invalidate_progress('listener_closed')
        if self._listener_close_attempted:
            return
        self._listener_close_attempted = True
        if self._socket is None:
            self._listener_closed = True
            return
        try:
            self._socket.close()
            self._listener_closed = self._socket.fileno() == -1
            if not self._listener_closed:
                self._fault('listener_close_unconfirmed')
        except BaseException as error:
            self._fault('listener_close_unconfirmed', error)

    def _driver_done(self, task):
        if task.cancelled():
            self._fault('driver_cancelled')
        elif task.exception() is not None:
            self._fault('driver_failed', task.exception())
        self._fence()
        self._ensure_close()

    def _ensure_close(self):
        if self._close_task is None:
            self._close_task = self._loop.create_task(self._finish_close())
            self._close_task.add_done_callback(self._close_done)

    def _close_done(self, task):
        if task.cancelled():
            self._fault('cleanup_cancelled')
        elif task.exception() is not None:
            self._fault('cleanup_failed', task.exception())

    def close(self):
        """Synchronous acceptance fence; not ControlTransport.aclose/host Stop."""
        self._owner()
        self._fence()
        self._ensure_close()

    async def _drive(self):
        while not self._closing:
            try:
                conn, _ = self._socket.accept()
            except (BlockingIOError, InterruptedError):
                await asyncio.sleep(self.poll_interval)
                continue
            # Store ownership before the next await or call that could fail.
            record = self._record = {'socket': conn, 'setup': None, 'pair': None,
                                     'handler': None, 'transferred': False,
                                     'cleanup': None, 'raw_close_attempted': False,
                                     'raw_closed': False}
            self.accepted += 1
            conn.setblocking(False)
            if self._closing:
                await self._reap(record)
                break
            record['setup'] = self._loop.create_task(self._open(sock=conn, limit=4097))
            try:
                await asyncio.wait_for(asyncio.shield(record['setup']), self.setup_timeout)
            except asyncio.TimeoutError:
                # A completed inner TimeoutError remains a setup failure; a
                # pending setup is retained and must still be joined on close.
                self._fault('setup_failed' if record['setup'].done() else 'setup_timeout')
                raise
            record['pair'] = record['setup'].result()
            if not self._closing:
                reader, writer = record['pair']
                handler = self.transport.admit(reader, writer)
                if handler is None:
                    self.refused += 1
                    self.transport.invalidate_progress('listener_refused')
                else:
                    record['handler'], record['transferred'] = handler, True
                    await asyncio.shield(handler)
            await self._reap(record)

    async def _join_completed(self, task, code):
        if task is None:
            return
        try:
            await asyncio.shield(task)
        except BaseException as error:
            if (not task.done()
                    or isinstance(error, asyncio.CancelledError) and not task.cancelled()):
                raise  # A cancelled waiter cannot forget the underlying task.
            self._fault(code, error)

    def _close_raw(self, record):
        if record['raw_close_attempted']:
            return
        record['raw_close_attempted'] = True
        try:
            record['socket'].close()
            record['raw_closed'] = record['socket'].fileno() == -1
            if not record['raw_closed']:
                self._fault('accepted_close_unconfirmed')
        except BaseException as error:
            self._fault('accepted_close_unconfirmed', error)

    async def _close_writer(self, writer, owned):
        if owned:
            writer.close()
        # No wait_for here: an observer timeout must not cancel this close wait.
        await writer.wait_closed()

    async def _reap(self, record):
        setup = record['setup']
        if setup is not None and record['pair'] is None:
            await self._join_completed(setup, 'setup_failed')
            if not setup.cancelled() and setup.exception() is None:
                record['pair'] = setup.result()
        if record['pair'] is None:
            self._close_raw(record)
            resolved = record['raw_closed']
        else:
            await self._join_completed(record['handler'], 'handler_failed')
            if record['cleanup'] is None:
                record['cleanup'] = self._loop.create_task(
                    self._close_writer(record['pair'][1], not record['transferred']))
            await self._join_completed(record['cleanup'], 'stream_close_unconfirmed')
            cleanup = record['cleanup']
            resolved = (cleanup.done() and not cleanup.cancelled() and cleanup.exception() is None
                        and record['socket'].fileno() == -1)
            if not resolved:
                self._fault('stream_close_unconfirmed')
        if resolved:
            if self._record is record:
                self._record = None
            if not record.get('progress_published', False):
                record['progress_published'] = True
                try:
                    self.transport.reaped_status(record['handler'])
                except BaseException as error:
                    self._fault('progress_publication_failed', error)
                    self._fence()
                    raise
        else:
            self._fence()
            raise RuntimeError('Accepted connection cleanup is unresolved')

    async def _finish_close(self):
        await self._join_completed(self._driver, 'driver_failed')
        if self._record is not None:
            await self._reap(self._record)

    async def aclose(self, *, timeout=2):
        self._owner()
        duration(timeout, 30)
        self.close()
        try:
            await asyncio.wait_for(asyncio.shield(self._close_task), timeout)
        except asyncio.TimeoutError:
            pass
        except Exception:
            # The retained task/private diagnostic and lifecycle expose failure.
            pass
        return self.lifecycle()

    def lifecycle(self):
        self._owner()
        record = self._record
        close_done = (self._close_task is not None and self._close_task.done()
                      and not self._close_task.cancelled() and self._close_task.exception() is None)
        resources_closed = (self._closing and self._listener_closed and close_done
                            and (self._driver is None or self._driver.done()) and record is None)
        return {'accepting': self._started and not self._closing,
                'listener_closed': self._listener_closed,
                'resources_closed': resources_closed,
                'clean_close': resources_closed and not self._faults,
                'accepted_connections': self.accepted, 'refused_connections': self.refused,
                'owned_connection_pending': record is not None,
                'setup_pending': bool(record and record['setup'] and not record['setup'].done()),
                'handler_pending': bool(record and record['handler'] and not record['handler'].done()),
                'faults': sorted(self._faults),
                'transport': self.transport.lifecycle(),
                'host_stop_requested_by_listener': False}
