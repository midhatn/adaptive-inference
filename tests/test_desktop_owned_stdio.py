"""Owned stdio acquisition/error tests using injected fake descriptors only."""
import types
import unittest
from unittest.mock import patch
from adaptive_inference.desktop import run_gui


def leaves(error):
    if isinstance(error, BaseExceptionGroup):
        return [leaf for item in error.exceptions for leaf in leaves(item)]
    return [error]


class OwnedStdioTests(unittest.TestCase):
    def fixture(self, *, construction_error=None, retire_error=None, close_errors=None):
        events, owners = [], []
        close_errors = close_errors or {}
        class Raw:
            def __init__(self, fd, mode=None, closefd=False):
                self.fd, self.closefd, self.closed = fd, closefd, False
                if closefd:
                    events.append(('acquire', fd))
                    if construction_error is not None and fd == 1:
                        raise construction_error
                    owners.append(self)
            def close(self):
                events.append(('owner_close', self.fd))
                self.closed = True
                if self.fd in close_errors:
                    raise close_errors[self.fd]
        class Buffer:
            def __init__(self, fd): self.raw = Raw(fd)
        class Text:
            def __init__(self, fd): self.buffer, self.closed = Buffer(fd), False
            def fileno(self): return self.buffer.raw.fd
            def close(self):
                events.append(('retire', self.fileno()))
                self.closed = True
                if retire_error is not None and self.fileno() == 1:
                    raise retire_error
        fake_io = types.SimpleNamespace(TextIOWrapper=Text, BufferedReader=Buffer,
                                        BufferedWriter=Buffer, FileIO=Raw)
        fake_sys = types.SimpleNamespace(stdin=Text(0), stdout=Text(1))
        return fake_io, fake_sys, owners, events

    def run_with(self, setup, body):
        fake_io, fake_sys, _, _ = setup
        with patch.object(run_gui, 'io', fake_io), patch.object(run_gui, 'sys', fake_sys):
            with run_gui.owned_startup_streams() as streams:
                body(streams)

    def test_standard_wrappers_retire_before_first_use_and_owners_close(self):
        setup = self.fixture()
        def body(streams):
            self.assertEqual([s.fd for s in streams], [0, 1])
            self.assertTrue(all(s.closefd for s in streams))
            self.assertTrue(setup[1].stdin.closed and setup[1].stdout.closed)
            self.assertFalse(any(s.closed for s in streams))
            setup[3].append(('body',))
        self.run_with(setup, body)
        self.assertTrue(all(s.closed for s in setup[2]))
        self.assertEqual(setup[3], [('acquire', 0), ('acquire', 1), ('retire', 1),
                                    ('retire', 0), ('body',), ('owner_close', 1), ('owner_close', 0)])

    def test_partial_acquisition_closes_only_successful_owner_and_keeps_error(self):
        error = OSError('injected second acquisition failure')
        setup = self.fixture(construction_error=error)
        with self.assertRaises(OSError) as caught:
            self.run_with(setup, lambda _: self.fail('body must not run'))
        self.assertIs(caught.exception, error)
        self.assertEqual(len(setup[2]), 1)
        self.assertTrue(setup[2][0].closed)
        self.assertEqual(setup[3][-3:], [('retire', 1), ('retire', 0), ('owner_close', 0)])

    def test_retirement_failure_stops_body_and_closes_both_owners(self):
        error = OSError('injected wrapper retirement failure')
        setup = self.fixture(retire_error=error)
        with self.assertRaises(BaseExceptionGroup) as caught:
            self.run_with(setup, lambda _: self.fail('body must not run'))
        self.assertEqual(leaves(caught.exception), [error])
        self.assertTrue(all(s.closed for s in setup[2]))
        self.assertTrue(setup[1].stdin.closed)

    def test_primary_and_both_cleanup_errors_are_retained(self):
        primary, output_error, input_error = [OSError(s) for s in ('body', 'output', 'input')]
        setup = self.fixture(close_errors={0: input_error, 1: output_error})
        def fail(_): raise primary
        with self.assertRaises(BaseExceptionGroup) as caught:
            self.run_with(setup, fail)
        self.assertEqual(leaves(caught.exception), [primary, output_error, input_error])
        self.assertTrue(all(s.closed for s in setup[2]))

    def test_wrong_descriptor_rejected_without_acquisition_or_closure(self):
        setup = self.fixture()
        setup[1].stdout.buffer.raw.fd = 9
        with self.assertRaises(RuntimeError):
            self.run_with(setup, lambda _: self.fail('body must not run'))
        self.assertEqual(setup[3], [])


if __name__ == '__main__': unittest.main()
