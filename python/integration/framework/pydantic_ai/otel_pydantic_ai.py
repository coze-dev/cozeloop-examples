# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import os
import asyncio
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

# OpenAI env
os.environ['OPENAI_BASE_URL'] = 'https://ark.cn-beijing.volces.com/api/v3' # use ark model url by default, from https://www.volcengine.com/docs/82379/1361424
os.environ['OPENAI_API_KEY'] = 'xxx'  # your api key
os.environ['OPENAI_MODEL_NAME'] = 'xxx' # your model name, like doubao-1-5-vision-pro-32k-250115

# OTEL env
os.environ["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] = "https://api.coze.cn/v1/loop/opentelemetry/v1/traces" # cozeloop otel endpoint
os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = "cozeloop-workspace-id=xxx,Authorization=Bearer pat_xxx" # set your 'spaceID' and 'pat or sat token'

# OpenInference auto-detection for pydantic_ai
try:
    from openinference.instrumentation.pydantic_ai import OpenInferenceSpanProcessor
    print("✅ OpenInference pydantic_ai instrumentation enabled")
except ImportError as e:
    print(f"⚠️  OpenInference pydantic_ai instrumentation import failed: {e}")
    print("Program will continue running, but without OTEL tracing functionality")

# OTEL configuration
otlp_exporter = OTLPSpanExporter(timeout=10)
trace.set_tracer_provider(TracerProvider())
trace.get_tracer_provider().add_span_processor(OpenInferenceSpanProcessor())
trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(otlp_exporter))
tracer = trace.get_tracer(__name__)


from pydantic_ai import Agent

async def main():
    # Initialize Pydantic AI Agent
    model = 'openai:' + os.environ['OPENAI_MODEL_NAME']
    agent = Agent(
        model=model,
        system_prompt='Be concise.',
        instrument=True, # Enable instrumentation
    )

    # Set custom span as the root span
    with tracer.start_as_current_span("pydantic_ai_root_span") as span:
        # Set cozeloop specific attribute for custom root span
        span.set_attribute("cozeloop.span_type", "custom")

        # Start agent
        print("Running Pydantic AI agent...")
        result = await agent.run('What is the capital of France?')
        print(f"Result: {result.output}")

if __name__ == "__main__":
    asyncio.run(main())
