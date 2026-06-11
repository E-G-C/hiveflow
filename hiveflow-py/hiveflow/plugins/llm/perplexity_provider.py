"""Perplexity LLM Provider - Sonar models via OpenAI-compatible API."""

from typing import Any

from hiveflow.plugins.llm.errors import LLMAuthError
from hiveflow.plugins.llm.openai_provider import OpenAIProvider
from hiveflow.plugins.llm.secrets import get_secret_backend


class PerplexityProvider(OpenAIProvider):
    """Perplexity Sonar provider using the OpenAI SDK compatibility layer."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        super().__init__(base_url=base_url, api_key=api_key)

    def _get_client(self) -> Any:
        """Lazy-initialize the OpenAI-compatible Perplexity async client."""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:
                raise ImportError("OpenAI SDK required. Install with: uv add openai") from exc

            secrets = get_secret_backend()
            api_key = self._api_key or secrets.get_secret("PERPLEXITY_API_KEY")
            if not api_key:
                raise LLMAuthError(
                    "Perplexity API key not configured. "
                    "Set PERPLEXITY_API_KEY or pass api_key.",
                    provider_id=self.plugin_id,
                )

            base_url = (
                self._base_url
                or secrets.get_secret("PERPLEXITY_BASE_URL")
                or "https://api.perplexity.ai"
            )
            self._client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url.rstrip("/"),
            )

        return self._client

    @property
    def plugin_id(self) -> str:
        return "perplexity"

    @property
    def description(self) -> str:
        return "Perplexity Sonar provider (OpenAI-compatible, web-grounded responses)"

    @property
    def supports_function_calling(self) -> bool:
        return False

    @property
    def supports_json_mode(self) -> bool:
        return True

    @property
    def supports_vision(self) -> bool:
        return False

    def get_available_models(self) -> list[str]:
        return [
            "sonar",
            "sonar-pro",
            "sonar-deep-research",
            "sonar-reasoning-pro",
        ]
