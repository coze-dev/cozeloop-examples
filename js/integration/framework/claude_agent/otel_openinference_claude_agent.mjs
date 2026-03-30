// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { createRequire } from "node:module";
const require = createRequire(import.meta.url);

const { NodeSDK } = require("@opentelemetry/sdk-node");
const { OTLPTraceExporter } = require("@opentelemetry/exporter-trace-otlp-proto");
const { BatchSpanProcessor } = require("@opentelemetry/sdk-trace-base");
const { resourceFromAttributes } = require("@opentelemetry/resources");
const { trace } = require("@opentelemetry/api");
const { ClaudeAgentSDKInstrumentation } = require("@arizeai/openinference-instrumentation-claude-agent-sdk");

import * as ClaudeAgentSDKModule from "@anthropic-ai/claude-agent-sdk";
import { z } from "zod";

// ==================== Configuration ====================

// Your Anthropic API key
process.env.ANTHROPIC_API_KEY = "sk-ant-***";

// CozeLoop OTLP endpoint config
process.env.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT = "https://api.coze.cn/v1/loop/opentelemetry/v1/traces"
process.env.OTEL_EXPORTER_OTLP_HEADERS = "cozeloop-workspace-id=***,Authorization=Bearer ***"

// ==================== OpenTelemetry Setup ====================

const otlpExporter = new OTLPTraceExporter({
  timeoutMillis: 10000,
});

// Create mutable copy for ESM manual instrumentation
const ClaudeAgentSDK = { ...ClaudeAgentSDKModule };

const instrumentation = new ClaudeAgentSDKInstrumentation();
instrumentation.manuallyInstrument(ClaudeAgentSDK);

const sdk = new NodeSDK({
  resource: resourceFromAttributes({
    "service.name": "claude-agent-cozeloop-demo",
  }),
  spanProcessors: [new BatchSpanProcessor(otlpExporter)],
  instrumentations: [instrumentation],
});

sdk.start();

const tracer = trace.getTracer("claude-agent-cozeloop-demo");

// ==================== Tool Definitions ====================

const { tool, createSdkMcpServer, query } = ClaudeAgentSDK;

const getWeather = tool(
  "get_weather",
  "Gets the current weather for a given city",
  { city: z.string().describe("The city name to get weather for") },
  async (args) => {
    const weatherData = {
      "San Francisco": "Foggy, 62°F",
      "New York": "Sunny, 75°F",
      "London": "Rainy, 55°F",
      "Tokyo": "Clear, 68°F",
    };
    const weather = weatherData[args.city] || "Weather data not available";
    return { content: [{ type: "text", text: `Weather in ${args.city}: ${weather}` }] };
  }
);

// ==================== Main ====================

async function main() {
  const weatherServer = createSdkMcpServer({
    name: "weather",
    version: "1.0.0",
    tools: [getWeather],
  });

  // Set custom root_span
  await tracer.startActiveSpan("root_span", async (span) => {
    span.setAttribute("cozeloop.span_type", "custom");

    try {
      for await (const message of query({
        prompt:
          "What's the weather like in San Francisco and Tokyo?",
        options: {
          model: "claude-sonnet-4-5-20250929",
          systemPrompt:
            "You are a friendly travel assistant who helps with weather information.",
          mcpServers: { weather: weatherServer },
          allowedTools: ["mcp__weather__get_weather"],
        },
      })) {
        if (message.type === "assistant") {
          console.log(message.message.content);
        }
      }
    } finally {
      span.end();
    }
  });

  await sdk.shutdown();
}

main().catch(console.error);
