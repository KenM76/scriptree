"""Tests for ``scriptree.shell.single_instance`` — the QLocalServer
hand-off that lets a second ``run_scriptreering`` launch join an
already-running primary instead of spinning up an isolated process.

Strategy
--------

We start a real ``PrimaryServer`` on a unique server name, attach a
spy slot to its ``messageReceived`` signal, and then call
``try_handoff`` from the same process (acting as a secondary).  The
QLocalServer/QLocalSocket pair is in-process so no actual subprocess
is needed — just a Qt event loop spun briefly via
``QApplication.processEvents()``.

To avoid name collisions between concurrent test runs, the server
name is overridden per test via monkeypatching ``_server_name``.
"""
from __future__ import annotations

import os
import time

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])

# Auto-dismiss any QMessageBox that pops up during the test session
# (e.g. unexpected error dialogs).  Without this, a stray .warning()
# call would block the test indefinitely waiting for human input.
def _autodismiss_messagebox():
    """Patch QMessageBox so its blocking calls return Ok / Yes
    immediately instead of running a modal dialog.  Tests can opt
    into testing dialog content by re-patching with a more specific
    expectation."""
    QMessageBox.warning = staticmethod(  # type: ignore[assignment]
        lambda *a, **kw: QMessageBox.StandardButton.Ok
    )
    QMessageBox.information = staticmethod(  # type: ignore[assignment]
        lambda *a, **kw: QMessageBox.StandardButton.Ok
    )
    QMessageBox.critical = staticmethod(  # type: ignore[assignment]
        lambda *a, **kw: QMessageBox.StandardButton.Ok
    )
    QMessageBox.question = staticmethod(  # type: ignore[assignment]
        lambda *a, **kw: QMessageBox.StandardButton.Yes
    )


_autodismiss_messagebox()


from scriptree.shell import single_instance  # noqa: E402


def _unique_name(base: str = "ScripTreeRing-test") -> str:
    """Per-test server name to avoid cross-test contention."""
    return f"{base}-{os.getpid()}-{int(time.time() * 1e6) % 1_000_000}"


def _pump(ms: int = 50) -> None:
    """Spin the Qt event loop briefly so QLocalSocket reads/writes can
    propagate."""
    end = time.time() + ms / 1000
    while time.time() < end:
        QCoreApplication.processEvents()
        time.sleep(0.005)


# ---------------------------------------------------------------------------
# messages_from_argv
# ---------------------------------------------------------------------------

class TestMessagesFromArgv:
    def test_no_args_yields_spawn_cell(self) -> None:
        msgs = single_instance.messages_from_argv(["run_scriptreering.bat"])
        assert msgs == [{"command": "spawn_cell"}]

    def test_ring_path_yields_load_ring(self, tmp_path) -> None:
        f = tmp_path / "x.scriptreering"
        f.write_text("{}")
        msgs = single_instance.messages_from_argv(
            ["run_scriptreering.bat", str(f)]
        )
        assert len(msgs) == 1
        assert msgs[0]["command"] == "load_ring"
        assert msgs[0]["path"] == os.path.abspath(str(f))

    def test_scriptreetree_yields_load_catalog(self, tmp_path) -> None:
        f = tmp_path / "x.scriptreetree"
        f.write_text("{}")
        msgs = single_instance.messages_from_argv(
            ["run_scriptreering.bat", str(f)]
        )
        assert msgs[0]["command"] == "load_catalog"
        assert msgs[0]["path"] == os.path.abspath(str(f))

    def test_scriptree_yields_load_catalog(self, tmp_path) -> None:
        f = tmp_path / "x.scriptree"
        f.write_text("{}")
        msgs = single_instance.messages_from_argv(
            ["run_scriptreering.bat", str(f)]
        )
        assert msgs[0]["command"] == "load_catalog"

    def test_dash_flags_are_skipped(self) -> None:
        """``--``-prefixed flags should not be turned into messages
        themselves, but positional paths after them remain valid.
        For example, ``--load-ring foo.scriptreering`` produces a
        single ``load_ring`` message — the flag is recognised by the
        primary's normal arg parser; the secondary's handoff just
        forwards the path."""
        msgs = single_instance.messages_from_argv(
            ["run_scriptreering.bat", "--autoload-rings",
             "--load-ring", "foo.scriptreering"]
        )
        # The flag itself is dropped, the .scriptreering path is
        # forwarded as a load_ring message.
        assert len(msgs) == 1
        assert msgs[0]["command"] == "load_ring"
        assert msgs[0]["path"].endswith("foo.scriptreering")

    def test_only_flags_falls_back_to_spawn_cell(self) -> None:
        msgs = single_instance.messages_from_argv(
            ["run_scriptreering.bat", "--autoload-rings", "--new-process"]
        )
        assert msgs == [{"command": "spawn_cell"}]


# ---------------------------------------------------------------------------
# Server name sanitisation
# ---------------------------------------------------------------------------

class TestServerName:
    def test_includes_user(self, monkeypatch) -> None:
        monkeypatch.setenv("USERNAME", "Ken")
        monkeypatch.setenv("USER", "ken")
        assert "Ken" in single_instance._server_name() or \
               "ken" in single_instance._server_name()

    def test_sanitises_special_chars(self, monkeypatch) -> None:
        monkeypatch.setenv("USERNAME", "weird<user>name")
        monkeypatch.setenv("USER", "weird<user>name")
        name = single_instance._server_name()
        # Only [A-Za-z0-9._-] survives; the angle brackets become _.
        assert "<" not in name and ">" not in name
        assert name.startswith("ScripTreeRing--")


# ---------------------------------------------------------------------------
# Primary server lifecycle
# ---------------------------------------------------------------------------

class TestPrimaryServerLifecycle:
    def test_listen_succeeds(self, monkeypatch) -> None:
        """``listen`` should succeed on a fresh server name and let us
        stop cleanly afterward."""
        monkeypatch.setattr(
            single_instance, "_server_name", lambda: _unique_name()
        )
        srv = single_instance.PrimaryServer()
        assert srv.listen() is True
        srv.stop()

    def test_listen_idempotent_after_stop(self, monkeypatch) -> None:
        """Calling ``listen`` after ``stop`` (with the same name) should
        succeed because ``QLocalServer.removeServer`` clears any stale
        socket file on POSIX and the named pipe is re-creatable on
        Windows after close."""
        name = _unique_name()
        monkeypatch.setattr(single_instance, "_server_name", lambda: name)
        srv1 = single_instance.PrimaryServer()
        assert srv1.listen() is True
        srv1.stop()
        _pump(50)
        srv2 = single_instance.PrimaryServer()
        assert srv2.listen() is True
        srv2.stop()


# ---------------------------------------------------------------------------
# try_handoff with a mocked QLocalSocket
# ---------------------------------------------------------------------------

class _FakeSocket:
    """A QLocalSocket-shaped stand-in for unit tests.  Records every
    write and replays a configurable list of acks back to the client."""

    def __init__(self, *, connected: bool = True,
                 acks: list[bytes] | None = None) -> None:
        from PySide6.QtNetwork import QLocalSocket
        self._connected = connected
        self._acks = list(acks) if acks else [b'{"ok":true}\n']
        self.writes: list[bytes] = []
        self._read_buf = b""
        self._error_string = "" if connected else "ConnectionRefusedError"
        # Expose the enum for state checks in code under test.
        self._State = QLocalSocket.LocalSocketState

    def connectToServer(self, name, mode=None) -> None:  # noqa: ANN001, D401
        pass

    def waitForConnected(self, ms: int) -> bool:
        return self._connected

    def write(self, data) -> int:
        b = bytes(data) if hasattr(data, "__bytes__") else data
        if hasattr(b, "data"):
            b = b.data().tobytes() if hasattr(b.data(), "tobytes") else bytes(b.data())
        self.writes.append(bytes(b))
        # On every write, queue the next ack from the script.
        if self._acks:
            self._read_buf += self._acks.pop(0)
        return len(b)

    def waitForBytesWritten(self, ms: int) -> bool:
        return True

    def waitForReadyRead(self, ms: int) -> bool:
        return bool(self._read_buf)

    def readAll(self):
        from PySide6.QtCore import QByteArray
        out = QByteArray(self._read_buf)
        self._read_buf = b""
        return out

    def disconnectFromServer(self) -> None:
        self._connected = False

    def state(self):
        from PySide6.QtNetwork import QLocalSocket
        return (
            QLocalSocket.LocalSocketState.UnconnectedState
            if not self._connected
            else QLocalSocket.LocalSocketState.ConnectedState
        )

    def waitForDisconnected(self, ms: int) -> bool:
        return True

    def errorString(self) -> str:
        return self._error_string


def _patch_qlocalsocket(monkeypatch, fake: _FakeSocket):
    """Patch ``single_instance.QLocalSocket`` with a callable that
    returns the fake but **preserves the LocalSocketState class
    attribute** (the production code reads
    ``QLocalSocket.LocalSocketState.UnconnectedState`` after disconnect)."""
    from PySide6.QtNetwork import QLocalSocket as _RealQLS

    class _PatchedQLS:
        LocalSocketState = _RealQLS.LocalSocketState
        def __new__(cls):
            return fake

    monkeypatch.setattr(single_instance, "QLocalSocket", _PatchedQLS)


class TestTryHandoffProtocol:
    def test_no_primary_returns_false(self, monkeypatch) -> None:
        """When ``waitForConnected`` returns False, ``try_handoff``
        must return False so the caller knows to start a primary
        itself."""
        _patch_qlocalsocket(monkeypatch, _FakeSocket(connected=False))
        ok = single_instance.try_handoff([{"command": "spawn_cell"}])
        assert ok is False

    def test_spawn_cell_writes_one_json_line(self, monkeypatch) -> None:
        sock = _FakeSocket(connected=True)
        _patch_qlocalsocket(monkeypatch, sock)
        ok = single_instance.try_handoff([{"command": "spawn_cell"}])
        assert ok is True
        assert len(sock.writes) == 1
        line = sock.writes[0].decode("utf-8")
        assert line.endswith("\n")
        import json as _json
        assert _json.loads(line.strip()) == {"command": "spawn_cell"}

    def test_multiple_messages_are_written_in_order(self, monkeypatch) -> None:
        sock = _FakeSocket(
            connected=True,
            acks=[b'{"ok":true}\n', b'{"ok":true}\n'],
        )
        _patch_qlocalsocket(monkeypatch, sock)
        msgs = [
            {"command": "spawn_cell"},
            {"command": "load_catalog", "path": "C:/x.scriptreetree"},
        ]
        ok = single_instance.try_handoff(msgs)
        assert ok is True
        assert len(sock.writes) == 2
        import json as _json
        assert _json.loads(sock.writes[0].decode("utf-8").strip())["command"] == "spawn_cell"
        assert _json.loads(sock.writes[1].decode("utf-8").strip())["command"] == "load_catalog"

    def test_primary_refusal_returns_false(self, monkeypatch) -> None:
        """If the primary acks ``ok=false``, try_handoff should return
        False so the caller sees the failure."""
        sock = _FakeSocket(
            connected=True,
            acks=[b'{"ok":false,"error":"bad command"}\n'],
        )
        _patch_qlocalsocket(monkeypatch, sock)
        ok = single_instance.try_handoff([{"command": "garbage"}])
        assert ok is False
