"""Tests for the credential store and prompt_credentials config field.

Covers:
- _SecureBytes encryption/decryption round-trip
- _SecureBytes clear zeroes memory
- StoredCredential create and get_password
- SessionCredentialStore put/get/remove/has/clear_all
- Configuration.prompt_credentials serialization round-trip
- prompt_credentials defaults to False
"""
from __future__ import annotations

import json

from scriptree.core.configs import (
    Configuration,
    ConfigurationSet,
    configs_from_dict,
    configs_to_dict,
)
from scriptree.core.credentials import (
    SessionCredentialStore,
    StoredCredential,
    _SecureBytes,
    get_session_store,
)


# --- _SecureBytes ----------------------------------------------------------


class TestSecureBytes:
    def test_round_trip(self) -> None:
        sb = _SecureBytes.from_plaintext("hello world")
        assert sb.decrypt() == "hello world"

    def test_unicode_round_trip(self) -> None:
        sb = _SecureBytes.from_plaintext("p\u00e4ssw\u00f6rd\U0001f511")
        assert sb.decrypt() == "p\u00e4ssw\u00f6rd\U0001f511"

    def test_empty_password(self) -> None:
        sb = _SecureBytes.from_plaintext("")
        assert sb.decrypt() == ""

    def test_clear_zeroes_cipher_and_pad(self) -> None:
        sb = _SecureBytes.from_plaintext("secret")
        assert len(sb._cipher) > 0
        sb.clear()
        assert all(b == 0 for b in sb._cipher)
        assert all(b == 0 for b in sb._pad)

    def test_cipher_differs_from_plaintext(self) -> None:
        text = "abc123"
        sb = _SecureBytes.from_plaintext(text)
        # The cipher bytes should not be identical to the UTF-8 encoding
        # (unless the pad happened to be all zeros, which is astronomically
        # unlikely for any length > 0).
        assert bytes(sb._cipher) != text.encode("utf-8")

    def test_different_instances_have_different_pads(self) -> None:
        a = _SecureBytes.from_plaintext("same")
        b = _SecureBytes.from_plaintext("same")
        # Different random pads means different ciphertexts.
        assert bytes(a._cipher) != bytes(b._cipher) or bytes(a._pad) != bytes(b._pad)


# --- StoredCredential ------------------------------------------------------


class TestStoredCredential:
    def test_create_and_get_password(self) -> None:
        cred = StoredCredential.create("admin", "hunter2", "CONTOSO")
        assert cred.username == "admin"
        assert cred.domain == "CONTOSO"
        assert cred.get_password() == "hunter2"

    def test_default_domain_empty(self) -> None:
        cred = StoredCredential.create("user", "pass")
        assert cred.domain == ""

    def test_clear_zeroes_password(self) -> None:
        cred = StoredCredential.create("u", "secret")
        cred.clear()
        # After clear, the internal bytes should be zeroed.
        assert all(b == 0 for b in cred._password._cipher)
        assert all(b == 0 for b in cred._password._pad)


# --- SessionCredentialStore ------------------------------------------------


class TestSessionCredentialStore:
    def test_put_and_get(self) -> None:
        store = SessionCredentialStore()
        cred = StoredCredential.create("alice", "pass1", "DOM")
        store.put("key1", cred)
        got = store.get("key1")
        assert got is not None
        assert got.username == "alice"
        assert got.get_password() == "pass1"
        assert got.domain == "DOM"

    def test_get_missing_returns_none(self) -> None:
        store = SessionCredentialStore()
        assert store.get("nonexistent") is None

    def test_has(self) -> None:
        store = SessionCredentialStore()
        assert not store.has("key")
        store.put("key", StoredCredential.create("u", "p"))
        assert store.has("key")

    def test_remove(self) -> None:
        store = SessionCredentialStore()
        cred = StoredCredential.create("u", "p")
        store.put("k", cred)
        store.remove("k")
        assert store.get("k") is None

    def test_remove_missing_is_noop(self) -> None:
        store = SessionCredentialStore()
        store.remove("nope")  # should not raise

    def test_put_replaces_and_clears_old(self) -> None:
        store = SessionCredentialStore()
        old = StoredCredential.create("u", "old_pass")
        store.put("k", old)
        new = StoredCredential.create("u", "new_pass")
        store.put("k", new)
        # The old credential's internal bytes should be zeroed.
        assert all(b == 0 for b in old._password._cipher)
        # The new one should work.
        got = store.get("k")
        assert got is not None
        assert got.get_password() == "new_pass"

    def test_clear_all(self) -> None:
        store = SessionCredentialStore()
        c1 = StoredCredential.create("a", "1")
        c2 = StoredCredential.create("b", "2")
        store.put("k1", c1)
        store.put("k2", c2)
        store.clear_all()
        assert store.get("k1") is None
        assert store.get("k2") is None
        # Both should be zeroed.
        assert all(b == 0 for b in c1._password._cipher)
        assert all(b == 0 for b in c2._password._cipher)


class TestGetSessionStore:
    def test_returns_same_singleton(self) -> None:
        s1 = get_session_store()
        s2 = get_session_store()
        assert s1 is s2


# --- prompt_credentials on Configuration -----------------------------------


class TestPromptCredentialsSerialization:
    def test_default_is_false(self) -> None:
        cfg = Configuration(name="test")
        assert cfg.prompt_credentials is False

    def test_round_trip_true(self) -> None:
        cfg_set = ConfigurationSet(
            active="test",
            configurations=[
                Configuration(name="test", prompt_credentials=True),
            ],
        )
        data = configs_to_dict(cfg_set)
        restored = configs_from_dict(data)
        assert restored.active_config().prompt_credentials is True

    def test_round_trip_false_omitted(self) -> None:
        """When prompt_credentials is False it should be omitted from JSON."""
        cfg_set = ConfigurationSet(
            active="test",
            configurations=[
                Configuration(name="test", prompt_credentials=False),
            ],
        )
        data = configs_to_dict(cfg_set)
        raw_cfg = data["configurations"][0]
        assert "prompt_credentials" not in raw_cfg

    def test_missing_key_defaults_false(self) -> None:
        """Legacy sidecars without prompt_credentials load as False."""
        data = {
            "schema_version": 1,
            "active": "default",
            "configurations": [
                {"name": "default", "values": {}, "extras": []},
            ],
        }
        restored = configs_from_dict(data)
        assert restored.active_config().prompt_credentials is False

    def test_explicit_true_in_json(self) -> None:
        data = {
            "schema_version": 1,
            "active": "admin",
            "configurations": [
                {
                    "name": "admin",
                    "values": {},
                    "extras": [],
                    "prompt_credentials": True,
                },
            ],
        }
        restored = configs_from_dict(data)
        assert restored.active_config().prompt_credentials is True
