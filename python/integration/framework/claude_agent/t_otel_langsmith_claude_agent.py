# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import os
import asyncio
import time

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    tool,
    create_sdk_mcp_server,
)
from typing import Any

# Your Anthropic API key
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-xxx"

# OpenTelemetry env
os.environ["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] = "https://api.coze.cn/v1/loop/opentelemetry/v1/traces" # cozeloop endpoint
os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = "cozeloop-workspace-id=xxx,Authorization=Bearer pat_xxx" # cozeloop space id, pat or sat token

# Configure LangChain OpenTelemetry instrumentation for Claude Agent SDK
os.environ["LANGSMITH_OTEL_ENABLED"] = "true"
os.environ["LANGSMITH_OTEL_ONLY"] = "true"
os.environ["LANGSMITH_TRACING"] = "true"


otlp_exporter = OTLPSpanExporter(
    timeout=10,
)
trace.set_tracer_provider(TracerProvider())
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(otlp_exporter)
)
tracer = trace.get_tracer(__name__)

from langsmith.integrations.claude_agent_sdk import configure_claude_agent_sdk # require langsmith version >= 0.5.0

# Configure Claude Agent SDK with OpenTelemetry tracing
configure_claude_agent_sdk()


@tool(
    "get_weather",
    "Gets the current weather for a given city",
    {
        "city": str,
    },
)
async def get_weather(args: dict[str, Any]) -> dict[str, Any]:
    """Simulated weather lookup tool"""
    city = args["city"]

    # Simulated weather data
    weather_data = {
        "San Francisco": "Foggy, 62°F",
        "New York": "Sunny, 75°F",
        "London": "Rainy, 55°F",
        "Tokyo": "Clear, 68°F",
    }

    weather = weather_data.get(city, "Weather data not available")
    return {"content": [{"type": "text", "text": f"Weather in {city}: {weather}"}]}


async def main():
    # Create SDK MCP server with the weather tool
    weather_server = create_sdk_mcp_server(
        name="weather",
        version="1.0.0",
        tools=[get_weather],
    )

    options = ClaudeAgentOptions(
        model="claude-sonnet-4-5-20250929",
        system_prompt="You are a friendly travel assistant who helps with weather information.",
        mcp_servers={"weather": weather_server},
        allowed_tools=["mcp__weather__get_weather"],
    )

    # Set custom span, name is root_span
    with tracer.start_as_current_span("root_span") as span:
        span.set_attribute("cozeloop.span_type", "custom")

        # Start Claude SDK client
        async with ClaudeSDKClient(options=options) as client:
            await client.query("What's the weather like in San Francisco and Tokyo?")

            async for message in client.receive_response():
                print(message)


if __name__ == "__main__":
    asyncio.run(main())
    time.sleep(2) # wait for ingest trace finish


