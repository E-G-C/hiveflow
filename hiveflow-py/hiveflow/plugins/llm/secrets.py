"""SecretBackend - Pluggable credential resolution for LLM providers.

Provides a protocol-based interface for sourcing credentials (API keys,
endpoints) from different backends. The default implementation reads
from environment variables. Custom implementations can source credentials
from external stores (AWS SSM, Azure Key Vault, HashiCorp Vault, etc.).

See: FR-017, data-model.md SecretBackend section, R8.
"""

import os
from typing import Protocol, runtime_checkable


@runtime_checkable
class SecretBackend(Protocol):
    """Pluggable credential resolution interface.

    Any class with a ``get_secret(key) -> str | None`` method satisfies
    this protocol via structural subtyping (no inheritance required).
    """

    def get_secret(self, key: str) -> str | None:
        """Resolve a secret by key name.

        Args:
            key: Secret identifier (e.g., "OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT").

        Returns:
            Secret value, or None if not found.
        """
        ...


class EnvVarBackend:
    """Default backend -- reads secrets from environment variables."""

    def get_secret(self, key: str) -> str | None:
        return os.environ.get(key)


_secret_backend: SecretBackend = EnvVarBackend()


def get_secret_backend() -> SecretBackend:
    """Return the active secret backend (default: ``EnvVarBackend``)."""
    return _secret_backend


def set_secret_backend(backend: SecretBackend) -> None:
    """Replace the active secret backend globally.

    Args:
        backend: Any object satisfying the ``SecretBackend`` protocol.
    """
    global _secret_backend  # noqa: PLW0603
    _secret_backend = backend
