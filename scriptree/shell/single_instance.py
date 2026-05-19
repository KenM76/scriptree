"""
single_instance.py — single-instance ScripTreeRing via QLocalServer.

## For humans

The default user experience when launching ``run_scriptreering.bat`` a
second time is **not** to start a new isolated process — that would
produce two cells that can't dock with each other (different
CellRegistry, different SnapEngine).  Instead the secondary
launch hands its argv to the already-running primary via a named
pipe (``QLocalServer``/``QLocalSocket``) and then exits.  The primary
spawns a sibling cell in its own process, so the new cell can snap
and dock with the existing ones.

The user can opt out of this behaviour with ``--new-process``, in
which case the secondary launches as a fully isolated instance.

Wire protocol
-------------

Each connection sends ONE JSON line terminated by ``\n``:

    {"command": "spawn_cell"}
    {"command": "load_ring", "path": "C:/full/path.scriptreering"}
    {"command": "load_catalog", "path": "C:/full/path.scriptreetree"}

The primary writes back a one-line JSON ack and closes:

    {"ok": true}
    {"ok": false, "error": "<message>"}

Server name
-----------

The server name is per-user so two users sharing the same machine each
get their own primary:

    ScripTreeRing--<sanitised-username>

Sanitisation strips characters Windows named pipes don't allow.  The
underlying QLocalServer namespace is the same on both POSIX (abstract
domain socket on Linux, ``/tmp`` socket on macOS) and Windows (named
pipe ``\\\\.\\pipe\\<name>``) — pick a name short enough for both.

## For maintainers / LLMs

* This is the single-instance guard.  ``try_handoff`` returning
  ``True`` means "every message acked by a live primary — caller MUST
  exit"; ``False`` means "no/stale primary — caller becomes the
  primary".  Any new failure path must return ``False`` (fail-open to
  starting a primary), never raise into ``main()``.
* The wire protocol is strictly line-delimited JSON: one object per
  ``\n``-terminated line, one ack per message, ack read before the
  next message is written.  A connection may deliver multiple lines in
  one chunk — ``_on_ready_read`` splits on ``splitlines()`` and acks
  each; ``try_handoff`` accumulates bytes until it sees ``\n``.  Keep
  both sides line-framed; do not switch to length-prefixing one side
  only.
* Timeouts are deliberately short (connect 1500 ms, write 1000 ms,
  read 1500 ms): a primary that doesn't answer in-window is treated as
  stale so the user isn't blocked behind a hung process.  The read
  loop polls in ≤200 ms slices and decrements ``deadline_left`` even
  on a spurious ``waitForReadyRead`` wakeup — preserve the decrement
  or a chatty-but-incomplete primary loops forever.
* ``listen()`` calls ``QLocalServer.removeServer(name)`` first: on
  POSIX this clears a stale socket file left by a crashed primary
  (idempotent, harmless on Windows).  On Windows a live primary still
  owns the named pipe so ``listen()`` then fails with
  ``AddressInUseError`` — that is the correct "another primary exists"
  signal, not an error to retry.
* RACE: ``removeServer`` then ``listen`` is not atomic.  Two processes
  racing to become primary on POSIX can both ``removeServer`` and one
  can unlink the other's just-bound socket.  The handoff path mitigates
  this (a started primary wins the pipe), but do not assume mutual
  exclusion is bulletproof under a simultaneous double-launch.
* ``messages_from_argv`` parses the extension via
  ``rsplit(".",1)[-1]`` (so ``foo.SCRIPTREERING`` works,
  case-insensitively) and ``os.path.abspath`` resolves paths against
  the *secondary's* CWD before sending — the primary may have a
  different CWD, so relative paths MUST be absolutised here, not on
  the primary side.
* Server name sanitisation (``[^A-Za-z0-9._-] → _``) is applied to the
  username AND the ``SCRIPTREERING_PIPE_NAME`` test override; the
  override exists so test drivers get an isolated pipe — keep it
  honoured before the username branch.
* ``PrimaryServer`` keeps ``self._connections`` to hold socket refs
  alive (GC would drop them mid-transfer); the ``disconnected`` lambda
  removes-if-present. Don't drop the list or in-flight acks can be
  lost to garbage collection.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from typing import Callable

from PySide6.QtCore import QByteArray, QIODevice, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


# ---------------------------------------------------------------------------
# Server-name derivation
# ---------------------------------------------------------------------------

def _server_name() -> str:
    """Return the per-user server name for ScripTreeRing.

    Honours ``SCRIPTREERING_PIPE_NAME`` for testing: setting that env
    var before launching ScripTreeRing forces a custom pipe name so a
    test driver can talk to its own primary without colliding with
    the user's live cell shell.
    """
    override = os.environ.get("SCRIPTREERING_PIPE_NAME")
    if override:
        return re.sub(r"[^A-Za-z0-9._-]", "_", override)
    if sys.platform == "win32":
        user = os.environ.get("USERNAME", "default")
    else:
        user = os.environ.get("USER", "default")
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", user)
    return f"ScripTreeRing--{safe}"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    print(f"[single_instance] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Secondary side — try to hand off to an already-running primary
# ---------------------------------------------------------------------------

# ConnectionTimeoutMs: short on purpose — if the primary's pipe doesn't
# respond within this window we assume it's gone (stale) and continue
# to start a fresh primary in this process.
_CONNECT_TIMEOUT_MS = 1500
_WRITE_TIMEOUT_MS = 1000
_READ_TIMEOUT_MS = 1500


def try_handoff(messages: list[dict]) -> bool:
    """Try to connect to a running primary and forward ``messages``.

    Returns True iff every message was acked.  False means there is
    no primary running (or it is unreachable / stale) and the caller
    should proceed to start a new primary.

    Each message is a dict (see module docstring for the schema).
    Multiple messages are sent on a single connection, one per line,
    each acked before the next is sent.
    """
    sock = QLocalSocket()
    sock.connectToServer(
        _server_name(), QIODevice.OpenModeFlag.ReadWrite,
    )
    if not sock.waitForConnected(_CONNECT_TIMEOUT_MS):
        _log(
            f"no primary on {_server_name()!r} "
            f"(error={sock.errorString()!r}); will start fresh"
        )
        return False
    _log(f"connected to primary on {_server_name()!r}")

    try:
        for msg in messages:
            line = json.dumps(msg, ensure_ascii=False) + "\n"
            sock.write(QByteArray(line.encode("utf-8")))
            if not sock.waitForBytesWritten(_WRITE_TIMEOUT_MS):
                _log(f"  write failed: {sock.errorString()!r}")
                return False
            # Read one line of ack.
            # M5 fix: the old loop only decremented the budget in the
            # waitForReadyRead-timed-out branch.  If the primary sent
            # a partial line then stalled, waitForReadyRead kept
            # returning True with no newline and the budget never
            # decremented → the secondary spun forever instead of
            # failing open.  Use a monotonic absolute deadline so
            # time is honoured regardless of which branch runs.
            ack = b""
            deadline = time.monotonic() + (_READ_TIMEOUT_MS / 1000.0)
            while b"\n" not in ack:
                remaining_ms = int(
                    (deadline - time.monotonic()) * 1000
                )
                if remaining_ms <= 0:
                    break
                if not sock.waitForReadyRead(min(remaining_ms, 200)):
                    continue
                ack += bytes(sock.readAll())  # type: ignore[arg-type]
            if b"\n" not in ack:
                _log("  ack timeout")
                return False
            try:
                resp = json.loads(ack.decode("utf-8").splitlines()[0])
            except Exception as exc:  # noqa: BLE001
                _log(f"  ack parse failed: {exc!r} (raw={ack!r})")
                return False
            if not resp.get("ok"):
                _log(f"  primary refused: {resp.get('error')!r}")
                return False
            _log(f"  ack {resp!r}")
        return True
    finally:
        sock.disconnectFromServer()
        if sock.state() != QLocalSocket.LocalSocketState.UnconnectedState:
            sock.waitForDisconnected(500)


# ---------------------------------------------------------------------------
# Primary side — listen for incoming hand-offs
# ---------------------------------------------------------------------------

class PrimaryServer(QObject):
    """QLocalServer wrapper that emits :py:attr:`messageReceived` for
    every JSON command sent by a secondary launch."""

    messageReceived = Signal(dict)  # one signal per message

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_new_connection)
        self._connections: list[QLocalSocket] = []

    def listen(self) -> bool:
        """Start listening on the per-user server name.  Returns True
        on success, False if another primary is already running.

        On Windows ``listen()`` will fail with
        ``QLocalServer.AddressInUseError`` when another primary holds
        the named pipe.  On POSIX a stale socket file may need to be
        removed first; ``QLocalServer.removeServer`` is idempotent.
        """
        name = _server_name()
        # M6 fix: the old order was unconditional ``removeServer``
        # THEN ``listen`` — on POSIX two processes racing to become
        # primary could BOTH ``removeServer`` and the second would
        # unlink the first's just-bound socket, so neither ends up a
        # usable primary.  Instead: try ``listen`` FIRST.  Only if it
        # fails (stale socket from a crashed prior primary, or a live
        # one) do we ``removeServer`` + retry once.  This never
        # blindly unlinks a *live* primary's socket; it narrows the
        # race window to the rare stale-socket recovery path.  (A
        # fully atomic bind isn't exposed by QLocalServer; this is
        # the standard Qt single-instance recovery pattern.)
        if self._server.listen(name):
            _log(f"primary listening on {name!r}")
            return True
        # listen() failed — could be a live primary (correct: we are
        # the secondary) or a stale socket file (recover it).
        QLocalServer.removeServer(name)
        if self._server.listen(name):
            _log(f"primary listening on {name!r} (after stale-socket recover)")
            return True
        _log(
            f"listen({name!r}) failed: "
            f"{self._server.errorString()!r}"
        )
        return False

    def stop(self) -> None:
        for sock in self._connections:
            try:
                sock.disconnectFromServer()
            except Exception:  # noqa: BLE001
                pass
        self._connections.clear()
        self._server.close()

    # -------------------------------------------------------------------
    # Connection handling
    # -------------------------------------------------------------------

    def _on_new_connection(self) -> None:
        while self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            self._connections.append(sock)
            sock.disconnected.connect(
                lambda s=sock: self._connections.remove(s)
                if s in self._connections else None
            )
            sock.readyRead.connect(lambda s=sock: self._on_ready_read(s))
            _log("primary: secondary connected")

    def _on_ready_read(self, sock: QLocalSocket) -> None:
        # A connection may deliver multiple lines in one chunk; process
        # each one and ack each one.
        chunk = bytes(sock.readAll())  # type: ignore[arg-type]
        if not chunk:
            return
        text = chunk.decode("utf-8", errors="replace")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                if not isinstance(msg, dict):
                    raise ValueError("expected JSON object")
                self.messageReceived.emit(msg)
                ack = {"ok": True}
            except Exception as exc:  # noqa: BLE001
                _log(f"  bad message {line!r}: {exc!r}")
                ack = {"ok": False, "error": str(exc)}
            ack_line = json.dumps(ack) + "\n"
            sock.write(QByteArray(ack_line.encode("utf-8")))
            sock.waitForBytesWritten(500)


# ---------------------------------------------------------------------------
# argv → message list
# ---------------------------------------------------------------------------

def messages_from_argv(argv: list[str]) -> list[dict]:
    """Derive the hand-off messages a secondary should forward to the
    primary, based on the secondary's argv.

    Rules:

    * Every positional ``.scriptreering`` path becomes a ``load_ring``
      message.
    * Every positional ``.scriptreetree`` / ``.scriptree`` path becomes
      a ``load_catalog`` message (primary spawns a cell bound to it).
    * If neither is present, a single ``spawn_cell`` message is sent so
      the user gets a sibling cell with no catalog bound.
    """
    msgs: list[dict] = []
    for arg in argv[1:]:
        if arg.startswith("-"):
            continue
        # L11 fix: was ``arg.lower().rsplit(".", 1)[-1]`` over the
        # WHOLE path — a path with a dot in a *directory* and no file
        # extension (``C:\my.dir\ring``) split to ``"dir\ring"`` → no
        # match → silently misclassified as a generic spawn.  Take
        # the extension of the basename only.
        ext = os.path.splitext(os.path.basename(arg))[1].lower().lstrip(".")
        if ext == "scriptreering":
            msgs.append({"command": "load_ring", "path": os.path.abspath(arg)})
        elif ext in ("scriptreetree", "scriptree"):
            msgs.append({"command": "load_catalog", "path": os.path.abspath(arg)})
    if not msgs:
        msgs.append({"command": "spawn_cell"})
    return msgs
