import type { ZodType } from "zod";

import type {
  FinishReason,
  ModelMessage,
  TokenUsage,
  ToolCall,
  ToolResult,
  WorkflowData
} from "./types.js";

export interface ToolExecutionContext {
  state: Readonly<WorkflowData>;
  messages: readonly ModelMessage[];
  agentId?: string;
  stepId?: string;
}

export interface ToolDefinition<TInput = unknown, TOutput = unknown> {
  description: string;
  inputSchema?: ZodType<TInput>;
  execute: (
    input: TInput,
    context: ToolExecutionContext
  ) => Promise<TOutput> | TOutput;
}

export interface ModelOutputDescriptor {
  kind: "text" | "structured";
  providerFormat?: unknown;
}

export type ToolExecutionMode = "auto" | "manual";

export interface ModelInvocationRequest {
  messages: ModelMessage[];
  state?: WorkflowData;
  temperature?: number;
  maxOutputTokens?: number;
  tools?: Record<string, ToolDefinition>;
  toolExecutionMode?: ToolExecutionMode;
  output?: ModelOutputDescriptor;
  metadata?: Record<string, unknown>;
}

export interface ModelCapabilities {
  streaming: boolean;
  toolCalls: boolean;
  structuredOutput: boolean;
}

export interface ModelInvocationResult {
  text: string;
  output?: unknown;
  finishReason?: FinishReason;
  usage?: TokenUsage;
  toolCalls: ToolCall[];
  toolResults: ToolResult[];
  responseMessages: ModelMessage[];
  raw?: unknown;
}

export type ModelStreamEvent =
  | {
      type: "text-delta";
      text: string;
    }
  | {
      type: "finish";
      finishReason?: FinishReason;
      usage?: TokenUsage;
      raw?: unknown;
    };

export interface ModelAdapter {
  id: string;
  capabilities: ModelCapabilities;
  generate(request: ModelInvocationRequest): Promise<ModelInvocationResult>;
  stream(request: ModelInvocationRequest): AsyncIterable<ModelStreamEvent>;
}