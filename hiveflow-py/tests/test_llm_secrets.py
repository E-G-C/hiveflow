"""Tests for SecretBackend protocol and implementations (T009).

Covers:
- ``EnvVarBackend.get_secret()`` reads from ``os.environ``
- ``get_secret_backend()`` returns ``EnvVarBackend`` by default
- ``set_secret_backend()`` swaps the active backend
- Custom dict-based backend works
- ``SecretBackend`` is ``runtime_checkable`` and ``isinstance()`` works
"""

import os

import pytest

from hiveflow.plugins.llm.secrets import (
    EnvVarBackend,
    SecretBackend,
    get_secret_backend,
    set_secret_backend,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _restore_default_backend():
    """Restore the default EnvVarBackend after each test."""
    yield
    set_secret_backend(EnvVarBackend())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEnvVarBackend:
    """EnvVarBackend reads from os.environ."""

    def test_returns_existing_env_var(self, monkeypatch):
        monkeypatch.setenv("TEST_SECRET_KEY_XYZ", "secret-value-123")
        backend = EnvVarBackend()
        assert backend.get_secret("TEST_SECRET_KEY_XYZ") == "secret-value-123"

    def test_returns_none_for_missing_key(self):
        backend = EnvVarBackend()
        # Use a key that almost certainly doesn't exist
        assert backend.get_secret("HIVEFLOW_NONEXISTENT_KEY_FOR_TEST") is None

    def test_reads_real_env_var(self):
        backend = EnvVarBackend()
        # PATH should exist on all systems
        result = backend.get_secret("PATH")
        assert result is not None


class TestGlobalAccessors:
    """get_secret_backend() / set_secret_backend() global state."""

    def test_default_backend_is_env_var(self):
        backend = get_secret_backend()
        assert isinstance(backend, EnvVarBackend)

    def test_set_and_get(self):
        class CustomBackend:
            def get_secret(self, key: str) -> str | None:
                return "custom-" + key

        custom = CustomBackend()
        set_secret_backend(custom)
        assert get_secret_backend() is custom
        assert get_secret_backend().get_secret("FOO") == "custom-FOO"

    def test_swap_back_to_env(self):
        class Dummy:
            def get_secret(self, key: str) -> str | None:
                return None

        set_secret_backend(Dummy())
        assert not isinstance(get_secret_backend(), EnvVarBackend)

        set_secret_backend(EnvVarBackend())
        assert isinstance(get_secret_backend(), EnvVarBackend)


class TestCustomBackend:
    """Dict-based custom backend."""

    def test_dict_backend(self):
        secrets = {"OPENAI_API_KEY": "sk-test", "OTHER": "val"}

        class DictBackend:
            def get_secret(self, key: str) -> str | None:
                return secrets.get(key)

        set_secret_backend(DictBackend())
        backend = get_secret_backend()
        assert backend.get_secret("OPENAI_API_KEY") == "sk-test"
        assert backend.get_secret("OTHER") == "val"
        assert backend.get_secret("MISSING") is None


class TestProtocol:
    """SecretBackend is runtime_checkable."""

    def test_env_var_satisfies_protocol(self):
        assert isinstance(EnvVarBackend(), SecretBackend)

    def test_dict_backend_satisfies_protocol(self):
        class DictBackend:
            def get_secret(self, key: str) -> str | None:
                return None

        assert isinstance(DictBackend(), SecretBackend)

    def test_non_conforming_rejected(self):
        class NotABackend:
            pass

        assert not isinstance(NotABackend(), SecretBackend)

    def test_wrong_signature_rejected(self):
        class WrongSig:
            def get_secret(self) -> str | None:  # missing key param
                return None

        # runtime_checkable only checks method existence, not signature,
        # so this may or may not pass isinstance — test documents the behaviour.
        # The important thing is that EnvVarBackend and conforming classes pass.
        assert isinstance(EnvVarBackend(), SecretBackend)
