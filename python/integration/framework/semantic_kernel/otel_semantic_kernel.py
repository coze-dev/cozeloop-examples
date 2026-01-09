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

# OTEL configuration
otlp_exporter = OTLPSpanExporter(timeout=10)
trace.set_tracer_provider(TracerProvider())
trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(otlp_exporter))
tracer = trace.get_tracer(__name__)

# OpenInference auto-detection for Semantic Kernel
try:
    from openinference.instrumentation.openai import OpenAIInstrumentor
    OpenAIInstrumentor().instrument()
    print("✅ OpenInference Semantic Kernel instrumentation enabled")
except ImportError as e:
    print(f"⚠️  OpenInference Semantic Kernel instrumentation import failed: {e}")
    print("Program will continue running, but without OTEL tracing functionality")

from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion

async def main():
    # Initialize the kernel
    kernel = Kernel()

    # Add OpenAI Chat Completion service
    kernel.add_service(
        OpenAIChatCompletion(
            service_id="chat-gpt",
            ai_model_id=os.environ['OPENAI_MODEL_NAME'],
        )
    )

    # Define a simple prompt
    prompt = "Tell me a short joke about a programmer."

    # Invoke the prompt
    print(f"Invoking prompt: {prompt}")

    # Set custom span, name is root_span
    with tracer.start_as_current_span("root_span") as span:
        span.set_attribute("cozeloop.span_type", "custom")

        # Start invoke kernel
        result = await kernel.invoke_prompt(prompt)

    print("\nResult:")
    print(result)

if __name__ == "__main__":
    asyncio.run(main())
