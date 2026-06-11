import { createOpenAI } from "@ai-sdk/openai";
import { generateText, streamText, tool as defineTool } from "ai";
import { z } from "zod";

import type {
  ModelAdapter,
  ModelCapabilities,
  ModelInvocationRequest,
  ModelInvocationResult,
  ModelMessage,
  ModelStreamEvent,
  ToolCall,
  ToolDefinition,
  ToolResult,
  TokenUsage
} from "@hiveflow/core";

type GenerateTextLike = (options: Record<string, unknown>) => Promise<unknown>;
type StreamTextLike = (options: Record<string, unknown>) => Promise<unknown> | unknown;

export interface AiSdkModelAdapterOptions {
  id: string;
  model: unknown;
  capabilities?: Partial<ModelCapabilities>;
  generateTextImpl?: GenerateTextLike;
  streamTextImpl?: StreamTextLike;
}

export interface OpenAICompatibleProviderFactoryConfig {
  baseURL?: string;
  apiKey?: string;
}

export interface OpenAICompatibleProvider {
  (modelId: string): unknown;
  chat?: (modelId: string) => unknown;
  responses?: (modelId: string) => unknown;
}

export type OpenAICompatibleApiMode = "chat" | "responses";

export interface OpenAICompatibleModelAdapterOptions {
  id?: string;
  modelId: string;
  baseURL?: string;
  apiKey?: string;
  apiMode?: OpenAICompatibleApiMode;
  capabilities?: Partial<ModelCapabilities>;
  generateTextImpl?: GenerateTextLike;
  streamTextImpl?: StreamTextLike;
  providerFactory?: (
    config: OpenAICompatibleProviderFactoryConfig
  ) => OpenAICompatibleProvider;
}

const DEFAULT_CAPABILITIES: ModelCapabilities = {
  streaming: true,
  toolCalls: true,
  structuredOutput: true
};

function normalizeUsage(usage: unknown): TokenUsage | undefined {
  if (!usage || typeof usage !== "object") {
    return undefined;
  }

  const record = usage as Record<string, unknown>;
  const inputTokens = Number(record.promptTokens ?? record.inputTokens ?? 0);
  const outputTokens = Number(record.completionTokens ?? record.outputTokens ?? 0);
  const totalTokens = Number(record.totalTokens ?? inputTokens + outputTokens);

  return {
    inputTokens,
    outputTokens,
    totalTokens
  };
}

function normalizeToolCall(toolCall: unknown): ToolCall {
  const record = (toolCall ?? {}) as Record<string, unknown>;

  return {
    id: String(record.toolCallId ?? record.id ?? ""),
    name: String(record.toolName ?? record.name ?? ""),
    input: record.input ?? record.args ?? record.arguments ?? {}
  };
}

function normalizeToolResult(toolResult: unknown): ToolResult {
  const record = (toolResult ?? {}) as Record<string, unknown>;

  return {
    toolCallId: String(record.toolCallId ?? record.id ?? ""),
    name: String(record.toolName ?? record.name ?? ""),
    output: record.output ?? record.result ?? record.value
  };
}

function extractTextContent(content: unknown): string {
  if (typeof content === "string") {
    return content;
  }

  if (!Array.isArray(content)) {
    return "";
  }

  return content
    .map((part) => {
      if (typeof part === "string") {
        return part;
      }

      if (part && typeof part === "object" && "text" in part) {
        const record = part as Record<string, unknown>;
        return typeof record.text === "string" ? record.text : "";
      }

      return "";
    })
    .filter(Boolean)
    .join("\n");
}

function normalizeResponseMessages(messages: unknown): ModelMessage[] {
  if (!Array.isArray(messages)) {
    return [];
  }

  return messages.map((message) => {
    const record = (message ?? {}) as Record<string, unknown>;
    const role = typeof record.role === "string" ? record.role : "assistant";

    return {
      role: role as ModelMessage["role"],
      content: extractTextContent(record.content)
    };
  });
}

function toAiSdkMessages(messages: ModelMessage[]): Record<string, unknown>[] {
  return messages.map((message) => {
    if (message.role === "assistant" && message.toolCalls && message.toolCalls.length > 0) {
      const content: Array<Record<string, unknown>> = [];

      if (message.content.length > 0) {
        content.push({
          type: "text",
          text: message.content
        });
      }

      for (const toolCall of message.toolCalls) {
        content.push({
          type: "tool-call",
          toolCallId: toolCall.id,
          toolName: toolCall.name,
          input: toolCall.input
        });
      }

      return {
        role: message.role,
        content
      };
    }

    if (message.role === "tool") {
      return {
        role: message.role,
        content: [
          {
            type: "tool-result",
            toolCallId: message.toolCallId ?? "",
            toolName: message.name ?? "",
            output: toToolResultOutput(message.content)
          }
        ]
      };
    }

    const payload: Record<string, unknown> = {
      role: message.role,
      content: message.content
    };

    if (message.name) {
      payload.name = message.name;
    }

    if (message.toolCallId) {
      payload.toolCallId = message.toolCallId;
    }

    if (message.toolCalls && message.toolCalls.length > 0) {
      payload.toolCalls = message.toolCalls.map((toolCall) => ({
        toolCallId: toolCall.id,
        toolName: toolCall.name,
        input: toolCall.input,
        args: toolCall.input
      }));
    }

    return payload;
  });
}

function parseSerializedToolContent(content: string): unknown {
  if (!content.trim()) {
    return "";
  }

  try {
    return JSON.parse(content);
  } catch {
    return content;
  }
}

function toToolResultOutput(content: string): Record<string, unknown> {
  const parsed = parseSerializedToolContent(content);

  if (typeof parsed === "string") {
    return {
      type: "text",
      value: parsed
    };
  }

  return {
    type: "json",
    value: parsed ?? null
  };
}

function toAiSdkTools(
  tools: Record<string, ToolDefinition> | undefined,
  request: ModelInvocationRequest
): Record<string, unknown> | undefined {
  if (!tools || Object.keys(tools).length === 0) {
    return undefined;
  }

  return Object.fromEntries(
    Object.entries(tools).map(([toolName, toolDefinition]) => [
      toolName,
      request.toolExecutionMode === "manual"
        ? defineTool({
            description: toolDefinition.description,
            inputSchema: toolDefinition.inputSchema ?? z.object({}),
            outputSchema: z.unknown()
          })
        : defineTool({
            description: toolDefinition.description,
            inputSchema: toolDefinition.inputSchema ?? z.object({}),
            execute: async (input: unknown) =>
              toolDefinition.execute(input, {
                state: request.state ?? {},
                messages: request.messages
              })
          })
    ])
  );
}

export class AiSdkModelAdapter implements ModelAdapter {
  public readonly capabilities: ModelCapabilities;

  private readonly generateTextImpl: GenerateTextLike;
  private readonly streamTextImpl: StreamTextLike;

  constructor(private readonly options: AiSdkModelAdapterOptions) {
    this.capabilities = {
      ...DEFAULT_CAPABILITIES,
      ...options.capabilities
    };
    this.generateTextImpl = options.generateTextImpl ?? (generateText as unknown as GenerateTextLike);
    this.streamTextImpl = options.streamTextImpl ?? (streamText as unknown as StreamTextLike);
  }

  get id(): string {
    return this.options.id;
  }

  async generate(request: ModelInvocationRequest): Promise<ModelInvocationResult> {
    const result = (await this.generateTextImpl(this.buildGenerateOptions(request))) as Record<
      string,
      unknown
    >;

    const normalized: ModelInvocationResult = {
      text: typeof result.text === "string" ? result.text : "",
      toolCalls: Array.isArray(result.toolCalls)
        ? result.toolCalls.map(normalizeToolCall)
        : [],
      toolResults: Array.isArray(result.toolResults)
        ? result.toolResults.map(normalizeToolResult)
        : [],
      responseMessages: normalizeResponseMessages(
        (result.response as Record<string, unknown> | undefined)?.messages
      ),
      raw: result
    };

    if (result.output !== undefined) {
      normalized.output = result.output;
    }

    if (typeof result.finishReason === "string") {
      normalized.finishReason = result.finishReason;
    }

    const usage = normalizeUsage(result.usage);
    if (usage) {
      normalized.usage = usage;
    }

    return normalized;
  }

  async *stream(request: ModelInvocationRequest): AsyncIterable<ModelStreamEvent> {
    const streamResult = (await this.streamTextImpl(
      this.buildGenerateOptions(request)
    )) as Record<string, unknown>;

    const textStream = streamResult.textStream;
    if (!textStream || !(Symbol.asyncIterator in Object(textStream))) {
      throw new Error("AI SDK streamText did not return an async textStream.");
    }

    for await (const chunk of textStream as AsyncIterable<unknown>) {
      yield {
        type: "text-delta",
        text: String(chunk)
      };
    }

    const finishEvent: ModelStreamEvent = {
      type: "finish",
      raw: streamResult
    };

    if (typeof streamResult.finishReason === "string") {
      finishEvent.finishReason = streamResult.finishReason;
    }

    const usage = normalizeUsage(streamResult.usage);
    if (usage) {
      finishEvent.usage = usage;
    }

    yield finishEvent;
  }

  private buildGenerateOptions(request: ModelInvocationRequest): Record<string, unknown> {
    const options: Record<string, unknown> = {
      model: this.options.model,
      messages: toAiSdkMessages(request.messages)
    };

    if (typeof request.temperature === "number") {
      options.temperature = request.temperature;
    }

    if (typeof request.maxOutputTokens === "number") {
      options.maxOutputTokens = request.maxOutputTokens;
      options.maxTokens = request.maxOutputTokens;
    }

    const tools = toAiSdkTools(request.tools, request);
    if (tools) {
      options.tools = tools;
    }

    if (request.output?.providerFormat !== undefined) {
      options.output = request.output.providerFormat;
    }

    if (request.metadata) {
      options.providerOptions = request.metadata;
    }

    return options;
  }
}

export function createAiSdkModelAdapter(options: AiSdkModelAdapterOptions): AiSdkModelAdapter {
  return new AiSdkModelAdapter(options);
}

function resolveOpenAICompatibleModel(
  provider: OpenAICompatibleProvider,
  modelId: string,
  apiMode: OpenAICompatibleApiMode
): unknown {
  if (apiMode === "responses" && typeof provider.responses === "function") {
    return provider.responses(modelId);
  }

  if (apiMode === "chat" && typeof provider.chat === "function") {
    return provider.chat(modelId);
  }

  return provider(modelId);
}

export function createOpenAICompatibleModelAdapter(
  options: OpenAICompatibleModelAdapterOptions
): AiSdkModelAdapter {
  const providerFactory = options.providerFactory ?? createOpenAI;
  const apiMode = options.apiMode ?? "chat";
  const providerConfig: OpenAICompatibleProviderFactoryConfig = {
    apiKey: options.apiKey ?? "not-needed"
  };

  if (options.baseURL) {
    providerConfig.baseURL = options.baseURL;
  }

  const provider = providerFactory(providerConfig);

  const adapterOptions: AiSdkModelAdapterOptions = {
    id: options.id ?? `openai-compatible:${options.modelId}`,
    model: resolveOpenAICompatibleModel(provider, options.modelId, apiMode)
  };

  if (options.capabilities) {
    adapterOptions.capabilities = options.capabilities;
  }

  if (options.generateTextImpl) {
    adapterOptions.generateTextImpl = options.generateTextImpl;
  }

  if (options.streamTextImpl) {
    adapterOptions.streamTextImpl = options.streamTextImpl;
  }

  return new AiSdkModelAdapter(adapterOptions);
}