"""Tests for tests/conftest.py's default-deny outbound-network guard.

Sibling of test_conftest_paper_isolation.py / test_conftest_tracker_db_isolation.py
-- the conftest machinery is real behaviour the whole suite leans on, so it gets
its own coverage rather than being trusted because other tests happen to pass.

Every address used here is RFC 5737 TEST-NET-1 (192.0.2.0/24), which is
guaranteed never to be routed. If the guard ever regresses, these tests fail on
a connect timeout instead of quietly reaching something real.

These are the only tests that should provoke the guard on purpose, so they are
also the only ones that use ``expect_blocked_network`` -- see its docstring.
"""

import socket

import pytest
import requests

from tests.conftest import (
    BlockedNetworkCall,
    _check_socket_address,
    expect_blocked_network,
)

_UNROUTABLE = "192.0.2.1"


def test_requests_call_is_blocked_and_the_error_names_the_url():
    """The requests chokepoint must fire, and its message must be actionable."""
    with expect_blocked_network() as excinfo:
        requests.get(f"https://{_UNROUTABLE}/v1/forecast", timeout=1)

    msg = str(excinfo.value)
    assert f"https://{_UNROUTABLE}/v1/forecast" in msg, (
        f"the blocked URL must appear in the error; got: {msg}"
    )
    assert "GET" in msg
    # The author needs to know WHICH test leaked and what to do about it.
    assert "test_requests_call_is_blocked_and_the_error_names_the_url" in msg
    assert "allow_network" in msg


def test_blocked_error_is_not_swallowed_by_except_exception():
    """The reason BlockedNetworkCall derives from BaseException.

    Production code wraps nearly every fetch in ``try/except Exception:
    log-and-continue``. If the guard raised an ``Exception`` subclass those
    handlers would swallow it, the test would pass, and the missing mock would
    stay invisible -- the exact failure this guard exists to end.
    """
    swallowed = []

    def _like_production_code():
        try:
            return requests.get(f"https://{_UNROUTABLE}/x", timeout=1)
        except Exception:  # noqa: BLE001 - mirrors the real resilience wrappers
            swallowed.append(True)
            return "fallback"

    with expect_blocked_network():
        _like_production_code()
    assert not swallowed, (
        "an `except Exception` handler caught the guard -- BlockedNetworkCall "
        "must not be an Exception subclass"
    )


def test_raw_socket_to_a_public_address_is_blocked():
    """The socket chokepoint covers callers that never touch requests
    (notify.py's urllib.request/smtplib posts, kalshi_ws.py's websocket)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    try:
        with expect_blocked_network() as excinfo:
            sock.connect((_UNROUTABLE, 443))
    finally:
        sock.close()
    assert _UNROUTABLE in str(excinfo.value)


def test_raw_socket_connect_ex_to_a_public_address_is_blocked():
    """connect_ex is a separate entry point from connect, and is separately
    patched -- without this, dropping that one line in conftest would leave
    every port-probe style caller unguarded and no test would notice."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    try:
        with expect_blocked_network() as excinfo:
            sock.connect_ex((_UNROUTABLE, 443))
    finally:
        sock.close()
    assert _UNROUTABLE in str(excinfo.value)


def test_loopback_socket_is_still_allowed():
    """Positive control for the two tests above: the socket guard must not be a
    blanket ban. A test standing up its own local server has to keep working,
    and without this those tests would also pass if ``connect`` were simply
    broken for every address."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.settimeout(5)
    try:
        client.connect(("127.0.0.1", port))  # must NOT raise
        conn, _ = server.accept()
        conn.close()
    finally:
        client.close()
        server.close()


def test_a_swallowed_block_still_fails_the_test():
    """The backstop for a block that never reaches pytest as an exception.

    An unhandled BlockedNetworkCall inside a plain threading.Thread target
    becomes a warning, not a failure, and a deliberate ``except BaseException``
    eats it outright -- either way the leak would be invisible again. So
    pytest_runtest_makereport fails a passing test that recorded a block.

    Asserted by running a one-test pytest session in-process, because the
    behaviour under test is precisely "this test would otherwise have passed".
    """
    inner = """
import threading
import requests

def test_leak_inside_a_thread():
    def _target():
        try:
            requests.get("https://192.0.2.1/leak", timeout=1)
        except Exception:
            pass

    t = threading.Thread(target=_target)
    t.start()
    t.join()
    assert True  # the test body itself succeeds
"""
    import subprocess
    import sys
    import tempfile
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory() as td:
        # Written into tests/ so it picks up the real conftest under test.
        probe = repo / "tests" / "test_zzz_swallowed_block_probe.py"
        probe.write_text(inner, encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", str(probe), "-q", "--no-header"],
                capture_output=True,
                text=True,
                cwd=str(repo),
                timeout=300,
            )
        finally:
            probe.unlink(missing_ok=True)
            del td

    assert proc.returncode != 0, (
        "a network call swallowed inside a thread must still fail the test;\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    assert "swallowed the failure" in proc.stdout, (
        f"expected the swallow-detector message; got:\n{proc.stdout}"
    )
    # Positive control: the probe really did reach the guard, rather than
    # failing for some unrelated reason (a collection error would also be a
    # non-zero exit).
    assert "192.0.2.1/leak" in proc.stdout, (
        f"the blocked URL must be reported; got:\n{proc.stdout}"
    )


def test_guard_is_installed_for_an_unmarked_test():
    """Positive control for the opt-out test below -- without it, that test
    would pass just as happily if the guard had stopped installing anything at
    all."""
    assert requests.adapters.HTTPAdapter.send.__name__ == "_blocked_send"
    assert socket.socket.connect.__name__ == "_blocked_connect"
    assert socket.socket.connect_ex.__name__ == "_blocked_connect_ex"


@pytest.mark.allow_network
def test_allow_network_marker_opts_out():
    """A test that genuinely needs the real network says so explicitly.

    Asserted by inspecting the patch state rather than by making a request:
    the point is that the guard stepped aside, not that the internet is up.
    """
    assert requests.adapters.HTTPAdapter.send.__name__ != "_blocked_send"
    assert socket.socket.connect.__name__ != "_blocked_connect"
    assert socket.socket.connect_ex.__name__ != "_blocked_connect_ex"


def test_guard_survives_a_test_calling_monkeypatch_undo(monkeypatch):
    """Three tests in this suite call monkeypatch.undo() mid-body, which
    reverts every setattr the shared function-scoped monkeypatch has recorded.
    The guard is installed on a session-scoped MonkeyPatch precisely so that
    cannot strip it (opus-review-caught)."""
    monkeypatch.setattr(socket, "AF_INET", socket.AF_INET)  # something to undo
    monkeypatch.undo()

    assert requests.adapters.HTTPAdapter.send.__name__ == "_blocked_send"
    assert socket.socket.connect.__name__ == "_blocked_connect"
    with expect_blocked_network():
        requests.get(f"https://{_UNROUTABLE}/after-undo", timeout=1)


@pytest.mark.parametrize(
    "address",
    [
        "/tmp/some.sock",  # AF_UNIX -- a plain str, not (host, port)
        bytes([0]) + b"abstract",  # AF_UNIX abstract namespace on Linux
        (0, 0),  # AF_NETLINK -- first element is an int, not a host
        (),  # degenerate, must not IndexError
        ("127.0.0.1", 8080),  # loopback
        ("::1", 8080, 0, 0),  # IPv6 loopback, 4-tuple
    ],
)
def test_non_remote_socket_addresses_are_let_through(address):
    """The address-shape branches of the socket check, which the behavioural
    tests above cannot reach. A false positive here would break AF_UNIX,
    netlink and IPv6-loopback callers rather than any real fetch."""
    assert _check_socket_address(address) is None


def test_blocked_network_call_is_not_an_exception_subclass():
    """Pins the class hierarchy itself, so a future edit to the base class is
    caught here and not only via the behavioural test above."""
    assert issubclass(BlockedNetworkCall, BaseException)
    assert not issubclass(BlockedNetworkCall, Exception)
