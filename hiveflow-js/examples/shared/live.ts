import { WorkflowRuntimeCatalog } from "@hiveflow/core";
import type { ArchetypeLibrary, ModelDefinition, ToolDefinition } from "@hiveflow/core";
import { createOpenAICompatibleModelAdapter } from "@hiveflow/provider-ai-sdk";
import type { OpenAICompatibleApiMode } from "@hiveflow/provider-ai-sdk";

export const LIVE_MODEL_KIND = "openai-compatible-live";
export const DEFAULT_LIVE_BASE_URL = "http://192.168.50.187:4000/v1";
export const DEFAULT_LIVE_MODEL_ID = "claude-opus-4-6";
export const DEFAULT_LIVE_TOOL_MODEL_ID = "claude-haiku-4-5";
export const DEFAULT_LIVE_API_MODE: OpenAICompatibleApiMode = "chat";

export interface LiveExampleConfig {
  baseURL: string;
  modelId: string;
  apiKey: string;
  apiMode: OpenAICompatibleApiMode;
}

export interface LiveExampleSummary {
  baseURL: string;
  modelId: string;
  apiMode: OpenAICompatibleApiMode;
}

export interface LiveRuntimeCatalogOptions {
  tools?: Record<string, ToolDefinition>;
  archetypeLibrary?: ArchetypeLibrary;
}

function readEnvironmentValue(name: string): string | undefined {
  const value = process.env[name];
  if (typeof value !== "string") {
    return undefined;
  }

  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

function normalizeApiMode(
  value: string | OpenAICompatibleApiMode | undefined
): OpenAICompatibleApiMode {
  return value === "responses" ? "responses" : "chat";
}

function readStringOption(options: Record<string, unknown>, key: string): string | undefined {
  const value = options[key];
  return typeof value === "string" && value.trim().length > 0 ? value : undefined;
}

export function resolveLiveExampleConfig(
  overrides: Partial<LiveExampleConfig> = {}
): LiveExampleConfig {
  return {
    baseURL:
      overrides.baseURL ??
      readEnvironmentValue("HIVEFLOW_LIVE_OPENAI_BASE_URL") ??
      DEFAULT_LIVE_BASE_URL,
    modelId:
      overrides.modelId ??
      readEnvironmentValue("HIVEFLOW_LIVE_OPENAI_MODEL") ??
      DEFAULT_LIVE_MODEL_ID,
    apiKey:
      overrides.apiKey ??
      readEnvironmentValue("HIVEFLOW_LIVE_OPENAI_API_KEY") ??
      "not-needed",
    apiMode: normalizeApiMode(
      overrides.apiMode ?? readEnvironmentValue("HIVEFLOW_LIVE_OPENAI_API_MODE")
    )
  };
}

export function summarizeLiveExampleConfig(
  overrides: Partial<LiveExampleConfig> = {}
): LiveExampleSummary {
  const config = resolveLiveExampleConfig(overrides);

  return {
    baseURL: config.baseURL,
    modelId: config.modelId,
    apiMode: config.apiMode
  };
}

export function createLiveModelAdapter(
  options: Partial<LiveExampleConfig> & { id?: string } = {}
) {
  const config = resolveLiveExampleConfig(options);

  return createOpenAICompatibleModelAdapter({
    id: options.id ?? `live-${config.modelId}`,
    baseURL: config.baseURL,
    apiKey: config.apiKey,
    modelId: config.modelId,
    apiMode: config.apiMode
  });
}

export function createLiveModelDefinition(
  options: Partial<LiveExampleConfig> & { id?: string } = {}
): ModelDefinition {
  const config = resolveLiveExampleConfig(options);

  return {
    kind: LIVE_MODEL_KIND,
    options: {
      id: options.id ?? `${LIVE_MODEL_KIND}-${config.modelId}`,
      baseURL: config.baseURL,
      modelId: config.modelId,
      apiMode: config.apiMode
    }
  };
}

export function createLiveRuntimeCatalog(
  options: LiveRuntimeCatalogOptions = {}
): WorkflowRuntimeCatalog {
  return new WorkflowRuntimeCatalog({
    tools: options.tools,
    archetypeLibrary: options.archetypeLibrary,
    modelFactories: {
      [LIVE_MODEL_KIND]: (definition) => {
        const definitionOptions = (definition.options ?? {}) as Record<string, unknown>;

        return createLiveModelAdapter({
          id: readStringOption(definitionOptions, "id"),
          baseURL: readStringOption(definitionOptions, "baseURL"),
          modelId: readStringOption(definitionOptions, "modelId"),
          apiKey: readStringOption(definitionOptions, "apiKey"),
          apiMode: normalizeApiMode(readStringOption(definitionOptions, "apiMode"))
        });
      }
    }
  });
}