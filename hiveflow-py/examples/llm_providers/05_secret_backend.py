"""Example: Custom Secret Backends.

Demonstrates how to:
1. Use the default EnvVarBackend (reads from os.environ)
2. Swap to a dictionary-based backend (e.g., for testing)
3. Build a Vault/SSM-style backend that could talk to a real secret store
4. Verify that all providers automatically pick up the new backend

No API keys needed -- this example shows the plumbing, not live calls.

Usage:
    uv run python examples/llm_providers/05_secret_backend.py
"""

from hiveflow.plugins.llm import (
    EnvVarBackend,
    SecretBackend,
    get_llm_registry,
    get_secret_backend,
    set_secret_backend,
)


def main() -> None:
    # -- 1. Default backend: environment variables ----------------------------
    print("1. Default backend")
    backend = get_secret_backend()
    print(f"   Type: {type(backend).__name__}")
    assert isinstance(backend, EnvVarBackend)
    print(f"   HOME = {backend.get_secret('HOME') or backend.get_secret('USERPROFILE')}")

    # -- 2. Dictionary backend (great for tests) ------------------------------
    print("\n2. Dictionary backend")

    class DictBackend:
        """In-memory secret store backed by a plain dict."""

        def __init__(self, secrets: dict[str, str]) -> None:
            self._secrets = secrets

        def get_secret(self, key: str) -> str | None:
            return self._secrets.get(key)

    test_secrets = {
        "OPENAI_API_KEY": "sk-test-not-a-real-key",
        "ANTHROPIC_API_KEY": "sk-ant-test-not-real",
        "AZURE_OPENAI_ENDPOINT": "https://my-resource.openai.azure.com",
        "AZURE_OPENAI_API_KEY": "azure-test-key-000",
    }
    set_secret_backend(DictBackend(test_secrets))

    current = get_secret_backend()
    print(f"   Type: {type(current).__name__}")
    print(f"   OPENAI_API_KEY = {current.get_secret('OPENAI_API_KEY')}")
    print(f"   MISSING_KEY    = {current.get_secret('MISSING_KEY')}")

    # Protocol check: DictBackend satisfies SecretBackend
    assert isinstance(current, SecretBackend)
    print("   Protocol check: passed")

    # -- 3. Vault-style backend (skeleton) ------------------------------------
    print("\n3. Vault-style backend (skeleton)")

    class VaultBackend:
        """Example: fetch secrets from HashiCorp Vault or AWS SSM.

        In a real implementation you'd call the Vault/SSM API here.
        The structural typing means you just need get_secret(key) -> str|None.
        """

        def __init__(self, prefix: str = "hiveflow/") -> None:
            self._prefix = prefix
            # Simulated vault contents
            self._store = {
                "hiveflow/OPENAI_API_KEY": "vault-resolved-openai-key",
                "hiveflow/AZURE_OPENAI_ENDPOINT": "https://prod.openai.azure.com",
            }

        def get_secret(self, key: str) -> str | None:
            return self._store.get(f"{self._prefix}{key}")

    set_secret_backend(VaultBackend())
    vb = get_secret_backend()
    print(f"   Type: {type(vb).__name__}")
    print(f"   OPENAI_API_KEY         = {vb.get_secret('OPENAI_API_KEY')}")
    print(f"   AZURE_OPENAI_ENDPOINT  = {vb.get_secret('AZURE_OPENAI_ENDPOINT')}")
    print(f"   ANTHROPIC_API_KEY      = {vb.get_secret('ANTHROPIC_API_KEY')}")

    # -- 4. Providers automatically use the active backend --------------------
    print("\n4. Providers use the active backend")
    print("   All providers call get_secret_backend().get_secret(key) at")
    print("   connection time, so swapping the backend before creating a")
    print("   provider client changes where credentials come from.")

    registry = get_llm_registry()
    print(f"   Available providers: {registry.list_ids()}")
    print("   (Each would use VaultBackend for its keys if called now)")

    # -- Restore default ------------------------------------------------------
    set_secret_backend(EnvVarBackend())
    print("\n   Restored default EnvVarBackend.")


if __name__ == "__main__":
    main()
