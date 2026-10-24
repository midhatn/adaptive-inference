"""Run against a pinned real Hermes checkout supplied by the test host."""
import os
import sys
from pathlib import Path
import socket
import pytest

UPSTREAM = Path(os.environ["HERMES_TEST_SOURCE"]).resolve()
sys.path.insert(0, str(UPSTREAM))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refused(*args, **kwargs):
        raise AssertionError("Contract tests must not open network connections")
    monkeypatch.setattr(socket.socket, "connect", refused)
    monkeypatch.setattr(socket.socket, "connect_ex", refused)
    monkeypatch.setattr(socket, "create_connection", refused)
