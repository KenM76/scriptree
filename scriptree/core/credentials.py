"""Secure session-scoped credential storage.

Credentials (username + password) are stored encrypted in memory using
a one-time pad generated at store time. This keeps plaintext passwords
out of Python's string intern pool and the immutable ``str`` heap.

Security properties:

- **No plaintext at rest in memory.** The password is XOR-encrypted
  with a random pad of equal length. Both pad and ciphertext are
  stored as ``bytearray`` (mutable) so they can be zeroed on clear.
- **Per-credential random pad.** Each stored credential gets its own
  pad from ``os.urandom``, so no key reuse.
- **Explicit wipe.** ``clear()`` overwrites every stored byte with
  zeros, then drops the references.
- **Session-scoped.** The store is an in-process singleton; nothing
  is written to disk.

Limitations:

- Python's GC may copy ``bytearray`` contents during reallocation.
  On CPython with reference-counted GC this is unlikely for
  fixed-size arrays, but not guaranteed.
- The username is stored as a plain string since it's not secret.
- ``os.urandom`` quality depends on the OS CSPRNG.

This module is pure Python, no Qt.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class _SecureBytes:
    """A password encrypted with a one-time pad.

    Call :meth:`decrypt` to get the plaintext back, :meth:`clear` to
    zero the memory.
    """

    _cipher: bytearray = field(repr=False)
    _pad: bytearray = field(repr=False)

    @classmethod
    def from_plaintext(cls, plaintext: str) -> "_SecureBytes":
        data = bytearray(plaintext.encode("utf-8"))
        pad = bytearray(os.urandom(len(data)))
        cipher = bytearray(a ^ b for a, b in zip(data, pad))
        # Wipe the plaintext copy we just made.
        for i in range(len(data)):
            data[i] = 0
        return cls(_cipher=cipher, _pad=pad)

    def decrypt(self) -> str:
        """Return the plaintext password."""
        plain = bytearray(a ^ b for a, b in zip(self._cipher, self._pad))
        try:
            return plain.decode("utf-8")
        finally:
            # Wipe the plaintext bytearray.
            for i in range(len(plain)):
                plain[i] = 0

    def clear(self) -> None:
        """Overwrite all stored bytes with zeros."""
        for i in range(len(self._cipher)):
            self._cipher[i] = 0
        for i in range(len(self._pad)):
            self._pad[i] = 0


@dataclass
class StoredCredential:
    """A username + encrypted password pair."""

    username: str
    domain: str  # empty string = local machine
    _password: _SecureBytes = field(repr=False)

    @classmethod
    def create(
        cls,
        username: str,
        password: str,
        domain: str = "",
    ) -> "StoredCredential":
        return cls(
            username=username,
            domain=domain,
            _password=_SecureBytes.from_plaintext(password),
        )

    def get_password(self) -> str:
        """Decrypt and return the password. Caller should use and discard."""
        return self._password.decrypt()

    def clear(self) -> None:
        """Zero out the encrypted password."""
        self._password.clear()


class SessionCredentialStore:
    """In-process, session-scoped credential store.

    Keys are arbitrary strings — typically the tool's file path or a
    ``(tool_path, config_name)`` tuple stringified. Each key maps to
    one ``StoredCredential``.

    Usage::

        store = SessionCredentialStore()

        # After the user enters credentials:
        store.put("tool_key", StoredCredential.create("user", "pass"))

        # Before running:
        cred = store.get("tool_key")
        if cred is not None:
            password = cred.get_password()
            # ... use password ...

        # On session end:
        store.clear_all()
    """

    def __init__(self) -> None:
        self._store: dict[str, StoredCredential] = {}

    def get(self, key: str) -> StoredCredential | None:
        """Return stored credential for ``key``, or None."""
        return self._store.get(key)

    def put(self, key: str, cred: StoredCredential) -> None:
        """Store a credential, replacing any existing one for ``key``."""
        old = self._store.get(key)
        if old is not None:
            old.clear()
        self._store[key] = cred

    def remove(self, key: str) -> None:
        """Remove and zero the credential for ``key``."""
        cred = self._store.pop(key, None)
        if cred is not None:
            cred.clear()

    def has(self, key: str) -> bool:
        return key in self._store

    def clear_all(self) -> None:
        """Zero and remove all stored credentials."""
        for cred in self._store.values():
            cred.clear()
        self._store.clear()


# Module-level singleton — lives for the process lifetime.
_session_store: SessionCredentialStore | None = None


def get_session_store() -> SessionCredentialStore:
    """Return the global session credential store (created on first call)."""
    global _session_store
    if _session_store is None:
        _session_store = SessionCredentialStore()
    return _session_store
