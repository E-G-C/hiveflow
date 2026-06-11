"""Example: Azure OpenAI with RBAC and API Key Authentication.

Demonstrates the two authentication paths for Azure OpenAI:
1. RBAC via DefaultAzureCredential (Entra ID) -- preferred for production
2. API key fallback -- simpler for development

The provider automatically picks the right path:
  - If AZURE_OPENAI_API_KEY is set -> API key auth
  - Otherwise -> RBAC via DefaultAzureCredential

Endpoint format:
  Use the *base* resource URL, not the full deployment URL.
  The provider auto-strips /openai/deployments/... if you paste the
  full URL from the Azure portal.

Prerequisites:
    - AZURE_OPENAI_ENDPOINT -- base resource URL
    - For RBAC: `az login`, managed identity, or service principal env vars
    - For API key: AZURE_OPENAI_API_KEY
    - `uv sync --extra llm-azure` (installs azure-identity)

Usage:
    # RBAC (recommended):
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
        uv run python examples/llm_providers/04_azure_rbac.py

    # API key:
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
    AZURE_OPENAI_API_KEY=abc123 \
        uv run python examples/llm_providers/04_azure_rbac.py

    # With a specific deployment name:
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
    AZURE_OPENAI_DEPLOYMENT=gpt-4o \
        uv run python examples/llm_providers/04_azure_rbac.py
"""

import asyncio
import os

from hiveflow.plugins.llm import LLMConfig, LLMMessage, get_llm_registry


async def main() -> None:
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    if not endpoint:
        print("Set AZURE_OPENAI_ENDPOINT to run this example.")
        print("  Example: AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com")
        return

    has_api_key = bool(os.environ.get("AZURE_OPENAI_API_KEY"))
    auth_mode = "API key" if has_api_key else "RBAC (DefaultAzureCredential)"
    print(f"Endpoint:  {endpoint}")
    print(f"Auth mode: {auth_mode}\n")

    registry = get_llm_registry()

    if "azure" not in registry.list_ids():
        print("Azure provider not available. Install with:")
        print("  uv sync --extra llm-azure")
        return

    # The model name in 'azure:<deployment>' is your Azure deployment name.
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
    provider, model = registry.resolve_model(f"azure:{deployment}")
    print(f"Deployment: {model}")
    print(f"Provider capabilities: streaming={provider.supports_streaming}, "
          f"tools={provider.supports_function_calling}, "
          f"vision={provider.supports_vision}\n")

    # -- 1. Simple chat --------------------------------------------------------
    messages = [
        LLMMessage(role="system", content="You are a helpful Azure-hosted assistant."),
        LLMMessage(role="user", content="What Azure region are you running in? Be brief."),
    ]
    config = LLMConfig(model=model, max_tokens=100, temperature=0.2)

    print("--- Chat ---")
    response = await provider.chat(messages, config)
    print(f"Response: {response.content}")
    print(f"Model:    {response.model}")
    if response.usage:
        print(f"Tokens:   {response.usage.total_tokens}")

    # -- 2. Streaming chat -----------------------------------------------------
    print("\n--- Streaming ---")
    messages = [
        LLMMessage(role="user", content="Count from 1 to 5, one number per line."),
    ]
    config = LLMConfig(model=model, max_tokens=50)

    print("Response: ", end="", flush=True)
    async for token in provider.chat_stream(messages, config):
        print(token, end="", flush=True)
    print()

    # -- 3. Full deployment URL auto-correction --------------------------------
    print("\n--- Endpoint normalization ---")
    print("If you paste the full deployment URL from the Azure portal, e.g.:")
    print(f"  {endpoint}/openai/deployments/{model}")
    print("the provider auto-strips the path. Both forms work identically.")


if __name__ == "__main__":
    asyncio.run(main())
