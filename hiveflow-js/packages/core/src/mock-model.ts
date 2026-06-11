import type {
  ModelAdapter,
  ModelCapabilities,
  ModelInvocationRequest,
  ModelInvocationResult,
  ModelStreamEvent
} from "./model.js";
import type { ModelMessage, TokenUsage, ToolCall, ToolResult } from "./types.js";

export interface MockModelResponse {
  text?: string;
  output?: unknown;
  finishReason?: string;
  usage?: Partial<TokenUsage>;
  toolCalls?: ToolCall[];
  toolResults?: ToolResult[];
  responseMessages?: ModelMessage[];
}

export type MockModelResponder = (
  request: ModelInvocationRequest,
  callIndex: number
) => Promise<MockModelResponse> | MockModelResponse;

const DEFAULT_CAPABILITIES: ModelCapabilities = {
  streaming: true,
  toolCalls: true,
  structuredOutput: true
};

function normalizeUsage(usage?: Partial<TokenUsage>): TokenUsage | undefined {
  if (!usage) {
    return undefined;
  }

  const inputTokens = usage.inputTokens ?? 0;
  const outputTokens = usage.outputTokens ?? 0;

  return {
    inputTokens,
    outputTokens,
    totalTokens: usage.totalTokens ?? inputTokens + outputTokens
  };
}

export class MockModelAdapter implements ModelAdapter {
  private invocationCount = 0;

  constructor(
    public readonly id: string,
    private readonly responder: MockModelResponder,
    public readonly capabilities: ModelCapabilities = DEFAULT_CAPABILITIES
  ) {}

  async generate(request: ModelInvocationRequest): Promise<ModelInvocationResult> {
    const callIndex = this.invocationCount;
    this.invocationCount += 1;

    const response = await this.responder(request, callIndex);

    const result: ModelInvocationResult = {
      text: response.text ?? "",
      toolCalls: response.toolCalls ?? [],
      toolResults: response.toolResults ?? [],
      responseMessages: response.responseMessages ?? request.messages,
      raw: response
    };

    if (response.output !== undefined) {
      result.output = response.output;
    }

    if (response.finishReason) {
      result.finishReason = response.finishReason;
    }

    const usage = normalizeUsage(response.usage);
    if (usage) {
      result.usage = usage;
    }

    return result;
  }

  async *stream(request: ModelInvocationRequest): AsyncIterable<ModelStreamEvent> {
    const result = await this.generate(request);
    const text = typeof result.output === "string" && !result.text ? result.output : result.text;

    for (const chunk of text) {
      yield {
        type: "text-delta",
        text: chunk
      };
    }

    const finishEvent: ModelStreamEvent = {
      type: "finish"
    };

    if (result.finishReason) {
      finishEvent.finishReason = result.finishReason;
    }

    if (result.usage) {
      finishEvent.usage = result.usage;
    }

    if (result.raw !== undefined) {
      finishEvent.raw = result.raw;
    }

    yield finishEvent;
  }
}

export function createMockModel(
  id: string,
  responder: MockModelResponder
): MockModelAdapter {
  return new MockModelAdapter(id, responder);
}