import { describe, expect, it } from "vitest";
import { z } from "zod";

import { AiSdkModelAdapter, createOpenAICompatibleModelAdapter } from "../src/index.js";

describe("AiSdkModelAdapter", () => {
  it("normalizes generateText results and exposes tool execution", async () => {
    let capturedOptions: Record<string, unknown> | undefined;
    const toolExecutions: unknown[] = [];

    const adapter = new AiSdkModelAdapter({
      id: "gateway-openai",
      model: "openai/gpt-5.4",
      generateTextImpl: async (options) => {
        capturedOptions = options;
        const tools = options.tools as Record<string, { execute: (input: unknown) => Promise<unknown> }>;
        const toolOutput = await tools.lookup.execute({ query: "status" });

        return {
          text: "All systems nominal.",
          finishReason: "stop",
          usage: {
            promptTokens: 10,
            completionTokens: 5,
            totalTokens: 15
          },
          toolCalls: [
            {
              toolCallId: "call-1",
              toolName: "lookup",
              args: { query: "status" }
            }
          ],
          toolResults: [
            {
              toolCallId: "call-1",
              toolName: "lookup",
              result: toolOutput
            }
          ],
          response: {
            messages: [
              {
                role: "assistant",
                content: [{ type: "text", text: "All systems nominal." }]
              }
            ]
          }
        };
      },
      streamTextImpl: async () => ({
        textStream: (async function* () {
          yield "unused";
        })()
      })
    });

    const result = await adapter.generate({
      messages: [
        {
          role: "user",
          content: "Check current platform status."
        }
      ],
      state: { environment: "test" },
      tools: {
        lookup: {
          description: "Look up service health.",
          inputSchema: z.object({ query: z.string() }),
          execute: async (input) => {
            const typedInput = input as { query: string };
            toolExecutions.push(typedInput);
            return { ok: true, query: typedInput.query };
          }
        }
      }
    });

    expect(capturedOptions?.model).toBe("openai/gpt-5.4");
    expect(toolExecutions).toEqual([{ query: "status" }]);
    expect(result.text).toBe("All systems nominal.");
    expect(result.toolCalls).toEqual([
      {
        id: "call-1",
        name: "lookup",
        input: { query: "status" }
      }
    ]);
    expect(result.toolResults).toEqual([
      {
        toolCallId: "call-1",
        name: "lookup",
        output: { ok: true, query: "status" }
      }
    ]);
    expect(result.usage).toEqual({
      inputTokens: 10,
      outputTokens: 5,
      totalTokens: 15
    });
    expect(result.responseMessages).toEqual([
      {
        role: "assistant",
        content: "All systems nominal."
      }
    ]);
  });

  it("emits normalized streaming events", async () => {
    const adapter = new AiSdkModelAdapter({
      id: "gateway-openai",
      model: "openai/gpt-5.4",
      generateTextImpl: async () => ({ text: "unused" }),
      streamTextImpl: async () => ({
        textStream: (async function* () {
          yield "Renewable";
          yield " energy";
        })(),
        finishReason: "stop",
        usage: {
          promptTokens: 2,
          completionTokens: 3,
          totalTokens: 5
        }
      })
    });

    const events = [];
    for await (const event of adapter.stream({
      messages: [
        {
          role: "user",
          content: "Stream a response."
        }
      ]
    })) {
      events.push(event);
    }

    expect(events).toEqual([
      {
        type: "text-delta",
        text: "Renewable"
      },
      {
        type: "text-delta",
        text: " energy"
      },
      {
        type: "finish",
        finishReason: "stop",
        usage: {
          inputTokens: 2,
          outputTokens: 3,
          totalTokens: 5
        },
        raw: {
          textStream: expect.anything(),
          finishReason: "stop",
          usage: {
            promptTokens: 2,
            completionTokens: 3,
            totalTokens: 5
          }
        }
      }
    ]);
  });

  it("can expose tool calls without executing them in manual tool mode", async () => {
    let capturedOptions: Record<string, unknown> | undefined;
    let toolExecuted = false;

    const adapter = new AiSdkModelAdapter({
      id: "gateway-openai",
      model: "openai/gpt-5.4",
      generateTextImpl: async (options) => {
        capturedOptions = options;
        return {
          text: "Plan the deployment action.",
          toolCalls: [
            {
              toolCallId: "call-1",
              toolName: "deploy",
              args: { environment: "staging" }
            }
          ],
          response: {
            messages: [
              {
                role: "assistant",
                content: [{ type: "text", text: "Plan the deployment action." }]
              }
            ]
          }
        };
      },
      streamTextImpl: async () => ({
        textStream: (async function* () {
          yield "unused";
        })()
      })
    });

    const result = await adapter.generate({
      messages: [
        {
          role: "user",
          content: "Plan a deployment action."
        }
      ],
      toolExecutionMode: "manual",
      tools: {
        deploy: {
          description: "Deploy the current release.",
          inputSchema: z.object({ environment: z.string() }),
          execute: async () => {
            toolExecuted = true;
            return { ok: true };
          }
        }
      }
    });

    const tools = capturedOptions?.tools as Record<string, Record<string, unknown>>;

    expect(toolExecuted).toBe(false);
    expect(tools.deploy.execute).toBeUndefined();
    expect(result.toolCalls).toEqual([
      {
        id: "call-1",
        name: "deploy",
        input: { environment: "staging" }
      }
    ]);
    expect(result.toolResults).toEqual([]);
  });

  it("falls back to the callable provider when helper methods are unavailable", async () => {
    const providerFactoryCalls: Array<Record<string, unknown>> = [];

    const adapter = createOpenAICompatibleModelAdapter({
      modelId: "local-model",
      baseURL: "http://192.168.50.187:4000/v1",
      providerFactory: (config) => {
        providerFactoryCalls.push(config as Record<string, unknown>);
        return (modelId) => ({ provider: "openai-compatible", modelId, config });
      },
      generateTextImpl: async (options) => ({
        text: "Live adapter ready.",
        response: {
          messages: [
            {
              role: "assistant",
              content: [{ type: "text", text: "Live adapter ready." }]
            }
          ]
        },
        debugModel: options.model
      }),
      streamTextImpl: async () => ({
        textStream: (async function* () {
          yield "ok";
        })()
      })
    });

    const result = await adapter.generate({
      messages: [
        {
          role: "user",
          content: "Ping"
        }
      ]
    });

    expect(providerFactoryCalls).toEqual([
      {
        baseURL: "http://192.168.50.187:4000/v1",
        apiKey: "not-needed"
      }
    ]);
    expect(result.text).toBe("Live adapter ready.");
    expect((result.raw as Record<string, unknown>).debugModel).toEqual({
      provider: "openai-compatible",
      modelId: "local-model",
      config: {
        baseURL: "http://192.168.50.187:4000/v1",
        apiKey: "not-needed"
      }
    });
  });

  it("prefers chat models by default for OpenAI-compatible providers", async () => {
    const adapter = createOpenAICompatibleModelAdapter({
      modelId: "claude-opus-4-6",
      providerFactory: () => {
        const provider = ((modelId: string) => ({ api: "default", modelId })) as {
          (modelId: string): unknown;
          chat: (modelId: string) => unknown;
          responses: (modelId: string) => unknown;
        };

        provider.chat = (modelId: string) => ({ api: "chat", modelId });
        provider.responses = (modelId: string) => ({ api: "responses", modelId });

        return provider;
      },
      generateTextImpl: async (options) => ({
        text: "ok",
        response: { messages: [] },
        debugModel: options.model
      }),
      streamTextImpl: async () => ({
        textStream: (async function* () {
          yield "ok";
        })()
      })
    });

    const result = await adapter.generate({
      messages: [
        {
          role: "user",
          content: "Ping"
        }
      ]
    });

    expect((result.raw as Record<string, unknown>).debugModel).toEqual({
      api: "chat",
      modelId: "claude-opus-4-6"
    });
  });

  it("allows callers to opt back into the responses API", async () => {
    const adapter = createOpenAICompatibleModelAdapter({
      modelId: "claude-opus-4-6",
      apiMode: "responses",
      providerFactory: () => {
        const provider = ((modelId: string) => ({ api: "default", modelId })) as {
          (modelId: string): unknown;
          chat: (modelId: string) => unknown;
          responses: (modelId: string) => unknown;
        };

        provider.chat = (modelId: string) => ({ api: "chat", modelId });
        provider.responses = (modelId: string) => ({ api: "responses", modelId });

        return provider;
      },
      generateTextImpl: async (options) => ({
        text: "ok",
        response: { messages: [] },
        debugModel: options.model
      }),
      streamTextImpl: async () => ({
        textStream: (async function* () {
          yield "ok";
        })()
      })
    });

    const result = await adapter.generate({
      messages: [
        {
          role: "user",
          content: "Ping"
        }
      ]
    });

    expect((result.raw as Record<string, unknown>).debugModel).toEqual({
      api: "responses",
      modelId: "claude-opus-4-6"
    });
  });
});