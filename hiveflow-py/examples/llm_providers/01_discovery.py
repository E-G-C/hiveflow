"""Example: Provider Discovery and Model Resolution.

Demonstrates how to:
1. Discover all installed LLM providers via entry points
2. Inspect provider capabilities (streaming, vision, function calling)
3. Resolve 'provider:model' references to provider instances
4. Handle missing-provider errors with install suggestions
5. List available models per provider

No API keys needed -- this example uses only local registry operations.

Usage:
    uv run python examples/llm_providers/01_discovery.py
"""

from hiveflow.plugins.llm import get_llm_registry


def main() -> None:
    registry = get_llm_registry()

    # -- 1. List discovered providers -----------------------------------------
    print("Discovered providers:", registry.list_ids())

    # -- 2. Inspect each provider's capabilities ------------------------------
    print("\nProvider capabilities:")
    for pid in registry.list_ids():
        provider = registry.get_or_raise(pid)
        caps = []
        if provider.supports_streaming:
            caps.append("streaming")
        if provider.supports_function_calling:
            caps.append("tools")
        if provider.supports_json_mode:
            caps.append("json_mode")
        if provider.supports_vision:
            caps.append("vision")
        models = provider.get_available_models() or ["(deployment names)"]
        print(f"  {pid}:")
        print(f"    description: {provider.description}")
        print(f"    capabilities: {', '.join(caps)}")
        print(f"    models: {', '.join(models)}")

    # -- 3. Resolve model references ------------------------------------------
    print("\nModel resolution:")
    for ref in ["openai:gpt-4o", "anthropic:claude-sonnet-4-20250514", "azure:my-deployment"]:
        provider, model = registry.resolve_model(ref)
        print(f"  '{ref}' -> provider={provider.provider_id}, model={model}")

    # -- 4. Error handling: missing provider with install hint ----------------
    print("\nMissing provider errors:")
    for bad_ref in ["google:gemini-2.0-flash", "ollama:llama3.3", "badformat"]:
        try:
            registry.resolve_model(bad_ref)
        except (KeyError, ValueError) as exc:
            print(f"  '{bad_ref}': {exc}")


if __name__ == "__main__":
    main()
