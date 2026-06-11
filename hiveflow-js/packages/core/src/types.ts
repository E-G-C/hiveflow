export type WorkflowData = Record<string, unknown>;

export type MessageRole = "system" | "user" | "assistant" | "tool";

export type FinishReason = "stop" | "tool-calls" | "length" | "error" | string;

export interface ToolCall {
  id: string;
  name: string;
  input: unknown;
}

export interface ToolResult {
  toolCallId: string;
  name: string;
  output: unknown;
}

export interface ModelMessage {
  role: MessageRole;
  content: string;
  name?: string;
  toolCallId?: string;
  toolCalls?: ToolCall[];
}

export interface TokenUsage {
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
}