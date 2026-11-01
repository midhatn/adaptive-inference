"""Bounded actual loopback sockets with the unchanged transport/fake runtime."""
import asyncio
import json
import socket
import unittest

from adaptive_inference.desktop.control_transport import ControlTransport, PreparedTask
from adaptive_inference.desktop.serial_listener import SerialListener

import test_desktop_control_transport as fixtures


def request(method='status', **changes):
    value = dict(host_epoch='host', session_id='session', task_id='task', token='a'*64, method=method)
    if method in ("pause", "resume", "cancel", "continue"):
        value.update(execution_id="task", execution_generation=0)
    value.update(changes)
    return (json.dumps(value, separators=(',', ':'))+'\n').encode()


class ListenerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.runtime = fixtures.Runtime()
        self.capability = object()
        self.transport = ControlTransport(PreparedTask('host', 'task', 'One unchanged objective'),
            self.runtime, capability=self.capability, runner_credential='b'*64, io_timeout=.1,
            max_handlers=1)
        self.transport.bind_session(self.capability, 'session', 'a'*64)
        self.listeners, self.clients, self.gates, self.raw_sockets = [], [], [], []

    def listener(self, **kwargs):
        async def tracked_open(**arguments):
            self.raw_sockets.append(arguments['sock'])
            return await asyncio.open_connection(**arguments)
        kwargs.setdefault('open_stream', tracked_open)
        value = SerialListener(self.transport, poll_interval=.005, **kwargs)
        self.listeners.append(value)
        value.start()
        return value

    async def client(self, listener):
        pair = await asyncio.wait_for(asyncio.open_connection(*listener.endpoint), 1)
        self.clients.append(pair[1])
        return pair

    async def eventually(self, predicate):
        deadline = asyncio.get_running_loop().time()+1.5
        while not predicate():
            if asyncio.get_running_loop().time() >= deadline:
                self.fail('Bounded condition did not arrive')
            await asyncio.sleep(.001)

    async def exchange(self, listener, data, *, eof=True):
        reader, writer = await self.client(listener)
        writer.write(data)
        await writer.drain()
        if eof:
            writer.write_eof()
        return await asyncio.wait_for(reader.read(), 1)

    async def close_listener(self, listener):
        result = await listener.aclose(timeout=1)
        self.assertTrue(result['resources_closed'], result)
        self.assertFalse(result['host_stop_requested_by_listener'])
        self.assertFalse(self.transport.lifecycle()['stop_requested'])
        return result

    async def asyncTearDown(self):
        for gate in self.gates:
            gate.set()
        for listener in self.listeners:
            listener.close()
        # Closing only test clients may unblock a held real request. This is
        # test cleanup, not a listener permission to cancel host work.
        for writer in self.clients:
            writer.close()
        for writer in self.clients:
            try:
                await asyncio.wait_for(writer.wait_closed(), 1)
            except (ConnectionError, OSError):
                pass
        for listener in self.listeners:
            state = await listener.aclose(timeout=1)
            self.assertTrue(state['resources_closed'], state)
        # Explicit fixture teardown only, AFTER listener semantics assertions.
        state = await self.transport.aclose(timeout=1)
        self.assertTrue(state['closed'], state)
        self.assertTrue(all(sock.fileno() == -1 for sock in self.raw_sockets))
        await asyncio.sleep(0)
        self.assertEqual(asyncio.all_tasks()-{asyncio.current_task()}, set())

    async def test_actual_lf_eof_authentication_status_and_pause(self):
        listener = self.listener()
        self.assertEqual(listener.endpoint[0], '127.0.0.1')
        ready = json.loads(await self.exchange(listener, request('window_ready')))
        self.assertEqual(ready, {'ok':True, 'state':'window_ready'})
        status = json.loads(await self.exchange(listener, request()))
        self.assertEqual(status['status']['objective'], 'One unchanged objective')
        pause = json.loads(await self.exchange(listener, request('pause', request_id='pause-one')))
        self.assertTrue(pause['control']['recorded'])
        self.assertFalse(pause['control']['owner_acknowledged'])
        self.assertEqual(self.runtime.commits, [('pause-one', 'pause')])
        result = await self.close_listener(listener)
        self.assertTrue(result['clean_close'])
        self.assertEqual(result['accepted_connections'], 3)

    async def test_bad_credentials_and_limits_never_dispatch(self):
        listener = self.listener()
        cases = [(request(token='c'*64), 'unauthorized'), (b'x'*4097, 'invalid_request'),
                 (request()+b'x', 'invalid_request'), (request()+request(), 'invalid_request')]
        for data, code in cases:
            with self.subTest(code=code, size=len(data)):
                value = json.loads(await self.exchange(listener, data))
                self.assertEqual(value, {'ok':False, 'error':code})
        self.assertEqual(self.runtime.commits, [])
        await self.close_listener(listener)

    async def test_newline_without_eof_times_out_without_dispatch(self):
        listener = self.listener()
        value = json.loads(await self.exchange(listener, request('pause', request_id='not-complete'), eof=False))
        self.assertEqual(value, {'ok':False, 'error':'request_timeout'})
        self.assertEqual(self.runtime.commits, [])
        await self.close_listener(listener)

    async def test_close_before_driver_starts_owns_listener(self):
        listener = self.listener()
        listener.close()
        result = await self.close_listener(listener)
        self.assertEqual(result['accepted_connections'], 0)
        with self.assertRaises(OSError):
            await asyncio.wait_for(asyncio.open_connection(*listener.endpoint), 1)

    async def test_pre_start_driver_cancellation_is_reaped(self):
        listener = self.listener()
        listener._driver.cancel()
        result = await self.close_listener(listener)
        self.assertIn('driver_cancelled', result['faults'])
        self.assertFalse(result['clean_close'])
        self.assertEqual(result['accepted_connections'], 0)

    async def test_idle_accept_close_has_no_pending_accept_future(self):
        listener = self.listener()
        await asyncio.sleep(.01)
        result = await self.close_listener(listener)
        self.assertEqual(result['accepted_connections'], 0)
        self.assertIsNone(listener._record)

    async def test_late_setup_after_close_is_joined_without_admission(self):
        entered, release = asyncio.Event(), asyncio.Event()
        self.gates.append(release)
        async def delayed(**arguments):
            self.raw_sockets.append(arguments['sock'])
            entered.set()
            await release.wait()
            return await asyncio.open_connection(**arguments)
        listener = self.listener(open_stream=delayed)
        await self.client(listener)
        await asyncio.wait_for(entered.wait(), 1)
        first = await listener.aclose(timeout=.01)
        self.assertFalse(first['resources_closed']); self.assertTrue(first['setup_pending'])
        self.assertFalse(listener._record['setup'].cancelled())
        release.set()
        result = await self.close_listener(listener)
        self.assertFalse(result['handler_pending']); self.assertEqual(self.runtime.commits, [])
        self.assertFalse(self.transport.lifecycle()['stop_requested'])

    async def test_setup_timeout_retains_late_result_and_failure(self):
        entered, release = asyncio.Event(), asyncio.Event()
        self.gates.append(release)
        async def delayed(**arguments):
            self.raw_sockets.append(arguments['sock'])
            entered.set(); await release.wait()
            return await asyncio.open_connection(**arguments)
        listener = self.listener(open_stream=delayed, setup_timeout=.02)
        await self.client(listener); await asyncio.wait_for(entered.wait(), 1)
        await self.eventually(lambda: 'setup_timeout' in listener.lifecycle()['faults'])
        self.assertFalse(listener._record['setup'].cancelled())
        release.set()
        result = await self.close_listener(listener)
        self.assertFalse(result['clean_close']); self.assertIn('setup_timeout', result['faults'])

    async def test_completed_setup_timeout_error_is_joined_failed_operation(self):
        async def failed(**arguments):
            self.raw_sockets.append(arguments['sock'])
            raise TimeoutError('fixture setup failed')
        listener = self.listener(open_stream=failed)
        await self.client(listener)
        await self.eventually(lambda: listener.lifecycle()['faults'])
        result = await self.close_listener(listener)
        self.assertIn('setup_failed', result['faults'])
        self.assertFalse(result['clean_close'])

    async def test_cancelled_close_waiter_keeps_cleanup_and_late_setup(self):
        entered, release = asyncio.Event(), asyncio.Event()
        self.gates.append(release)
        async def delayed(**arguments):
            self.raw_sockets.append(arguments['sock']); entered.set()
            await release.wait()
            return await asyncio.open_connection(**arguments)
        listener = self.listener(open_stream=delayed)
        await self.client(listener); await asyncio.wait_for(entered.wait(), 1)
        waiter = asyncio.create_task(listener.aclose(timeout=1))
        await self.eventually(lambda: listener._close_task is not None)
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError): await waiter
        self.assertFalse(listener._close_task.cancelled())
        self.assertFalse(listener._record['setup'].cancelled())
        release.set(); await self.close_listener(listener)

    async def test_driver_cancelled_during_setup_reaps_late_writer(self):
        entered, release = asyncio.Event(), asyncio.Event()
        self.gates.append(release)
        async def delayed(**arguments):
            self.raw_sockets.append(arguments['sock']); entered.set()
            await release.wait()
            return await asyncio.open_connection(**arguments)
        listener = self.listener(open_stream=delayed)
        await self.client(listener); await asyncio.wait_for(entered.wait(), 1)
        listener._driver.cancel()
        await self.eventually(lambda: listener._close_task is not None)
        self.assertFalse(listener._record['setup'].cancelled())
        release.set()
        result = await self.close_listener(listener)
        self.assertIn('driver_cancelled', result['faults'])

    async def test_close_during_handler_does_not_cancel_retained_mutation(self):
        listener = self.listener()
        await self.exchange(listener, request('window_ready'))
        self.runtime.release = asyncio.Event(); self.gates.append(self.runtime.release)
        reader, writer = await self.client(listener)
        writer.write(request('pause', request_id='held')); await writer.drain(); writer.write_eof()
        await asyncio.wait_for(self.runtime.entered.wait(), 1)
        result = await self.close_listener(listener)
        self.assertEqual(result['transport']['pending_mutations'], 1)
        self.assertEqual(self.runtime.commits, [])
        reply = json.loads(await asyncio.wait_for(reader.read(), 1))
        self.assertIsNone(reply['recorded'])
        self.runtime.release.set()
        await self.eventually(lambda: self.transport.lifecycle()['pending_mutations'] == 0)
        self.assertEqual(self.runtime.commits, [('held', 'pause')])
        self.assertFalse(self.transport.lifecycle()['stop_requested'])

    async def test_cancelled_admitted_handler_keeps_transport_cleanup_owner(self):
        listener = self.listener()
        await self.client(listener)
        await self.eventually(lambda: listener._record is not None and listener._record['handler'] is not None)
        handler = listener._record['handler']
        handler.cancel()
        result = await self.close_listener(listener)
        self.assertFalse(result['clean_close'])
        await self.eventually(lambda: self.transport.lifecycle()['pending_connections'] == 0)

    async def test_refused_connection_closed_before_next_accept_no_rejection_queue(self):
        held_reader = fixtures.Reader(eof=False)
        held_writer = fixtures.Writer()
        held = self.transport.admit(held_reader, held_writer)
        listener = self.listener()
        try:
            data = await self.exchange(listener, request())
        except ConnectionResetError:
            # Closing an unread refused request may reset the connection:
            # https://www.rfc-editor.org/rfc/rfc9293.html#section-3.6.1
            pass
        else:
            self.assertEqual(data, b'')
        await self.eventually(lambda: listener._record is None)
        self.assertEqual(listener.lifecycle()['refused_connections'], 1)
        self.assertEqual(len(self.transport._connections), 1)
        held_reader.eof.set()
        await asyncio.wait_for(asyncio.shield(held), 1)
        await self.eventually(lambda: self.transport.lifecycle()['pending_connections'] == 0)
        value = json.loads(await self.exchange(listener, request()))
        self.assertTrue(value['ok'])
        await self.close_listener(listener)

    async def test_close_before_start_cannot_restart_or_stop_host(self):
        listener = SerialListener(self.transport)
        self.listeners.append(listener)
        result = await self.close_listener(listener)
        self.assertTrue(result['clean_close'])
        with self.assertRaises(RuntimeError): listener.start()

    async def test_accept_return_after_reentrant_close_is_owned_and_reaped(self):
        accepted = []
        class ListenerSocket:
            def __init__(inner): inner.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            def __getattr__(inner, name): return getattr(inner.sock, name)
            def accept(inner):
                value = inner.sock.accept()
                accepted.append(value[0])
                listener.close()  # Deliberate test-only callback before return.
                return value
        listener = self.listener(socket_factory=ListenerSocket)
        await self.client(listener)
        await self.eventually(lambda: bool(accepted))
        result = await self.close_listener(listener)
        self.assertEqual(result['accepted_connections'], 1)
        self.assertEqual(accepted[0].fileno(), -1)
        self.assertEqual(self.raw_sockets, [])
        self.assertEqual(self.runtime.commits, [])

    async def test_refused_writer_cleanup_is_retained_across_close_timeout(self):
        release = asyncio.Event(); self.gates.append(release)
        entered = asyncio.Event(); writers = []
        class Writer:
            def __init__(inner, actual): inner.actual=actual; inner.closes=0; inner.waits=0
            def __getattr__(inner, name): return getattr(inner.actual, name)
            def close(inner): inner.closes+=1; inner.actual.close()
            async def wait_closed(inner):
                inner.waits+=1
                await inner.actual.wait_closed()
                entered.set()
                await release.wait()
        async def delayed_close(**arguments):
            self.raw_sockets.append(arguments['sock'])
            reader, writer = await asyncio.open_connection(**arguments)
            wrapper = Writer(writer); writers.append(wrapper)
            return reader, wrapper
        held_reader = fixtures.Reader(eof=False)
        held = self.transport.admit(held_reader, fixtures.Writer())
        listener = self.listener(open_stream=delayed_close)
        await self.client(listener); await asyncio.wait_for(entered.wait(), 1)
        state = await listener.aclose(timeout=.01)
        self.assertFalse(state['resources_closed'])
        self.assertIsNotNone(listener._record['cleanup'])
        self.assertFalse(listener._record['cleanup'].cancelled())
        self.assertEqual(writers[0].closes, 1)
        held_reader.eof.set(); await asyncio.wait_for(asyncio.shield(held), 1)
        release.set(); await self.close_listener(listener)
        self.assertEqual(writers[0].closes, 1); self.assertEqual(writers[0].waits, 1)

    async def test_start_failure_preserves_original_and_closes_owned_socket(self):
        class ListenerSocket:
            def __init__(inner): inner.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            def __getattr__(inner, name): return getattr(inner.sock, name)
            def bind(inner, address): raise OSError('original bind failure')
        sock = ListenerSocket()
        listener = SerialListener(self.transport, socket_factory=lambda:sock)
        self.listeners.append(listener)
        with self.assertRaisesRegex(OSError, 'original bind failure'): listener.start()
        result = await self.close_listener(listener)
        self.assertEqual(sock.fileno(), -1)
        self.assertIn('start_failed', result['faults'])
        self.assertFalse(result['clean_close'])

    async def test_stop_is_only_the_authenticated_transport_action(self):
        listener = self.listener()
        value = json.loads(await self.exchange(listener, request('stop')))
        self.assertTrue(value['stop_requested'])
        await self.eventually(lambda:self.transport.lifecycle()['stop_confirmed'])
        result = await listener.aclose(timeout=1)
        self.assertTrue(result['resources_closed'])
        self.assertTrue(result['transport']['stop_requested'])
        self.assertFalse(result['host_stop_requested_by_listener'])

    async def test_start_and_close_failures_keep_primary_and_secondary(self):
        class ListenerSocket:
            def __init__(inner): inner.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM); inner.closes=0
            def __getattr__(inner, name): return getattr(inner.sock, name)
            def bind(inner, address): raise OSError('original bind failure')
            def close(inner):
                inner.closes+=1
                inner.sock.close()
                raise OSError('injected close uncertainty')
        sock = ListenerSocket()
        listener = SerialListener(self.transport, socket_factory=lambda:sock)
        with self.assertRaisesRegex(OSError, 'original bind failure'): listener.start()
        state = await listener.aclose(timeout=1)
        self.assertFalse(state['resources_closed']); self.assertFalse(state['clean_close'])
        self.assertEqual(state['faults'], ['listener_close_unconfirmed', 'start_failed'])
        self.assertIn('original bind failure', str(listener._exceptions['start_failed']))
        self.assertIn('injected close uncertainty', str(listener._exceptions['listener_close_unconfirmed']))
        self.assertEqual(sock.fileno(), -1)  # Fixture actually reaped the OS socket.
        self.assertEqual(sock.closes, 1)  # No blind retry or fabricated closure proof.
        self.assertFalse(self.transport.lifecycle()['stop_requested'])

    async def test_cancelled_join_waiter_does_not_absorb_success_race(self):
        listener = self.listener()
        child = asyncio.create_task(asyncio.sleep(0))
        waiter = asyncio.create_task(listener._join_completed(child, 'fixture_failed'))
        # Make cancellation win the observer while the child's actual result is
        # successful. The retained child stays available to the close owner.
        child.add_done_callback(lambda done: waiter.cancel())
        with self.assertRaises(asyncio.CancelledError): await waiter
        self.assertTrue(child.done()); self.assertFalse(child.cancelled())
        self.assertNotIn('fixture_failed', listener.lifecycle()['faults'])
        await self.close_listener(listener)


if __name__ == '__main__':
    unittest.main()
