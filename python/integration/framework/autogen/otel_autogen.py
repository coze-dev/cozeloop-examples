# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import os
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
otlp_exporter = OTLPSpanExporter(
    timeout=10,
)
trace.set_tracer_provider(TracerProvider())
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(otlp_exporter)
)
tracer = trace.get_tracer(__name__)

# OpenInference auto-detection for AutoGen
try:
    from openinference.instrumentation.autogen import AutogenInstrumentor
    from openinference.instrumentation.openai import OpenAIInstrumentor
    AutogenInstrumentor().instrument()
    OpenAIInstrumentor().instrument()
    print("✅ OpenInference AutoGen instrumentation enabled")
except ImportError as e:
    print(f"⚠️  OpenInference AutoGen instrumentation import failed: {e}")
    print("Program will continue running, but without OTEL tracing functionality")

from autogen import AssistantAgent, UserProxyAgent

def main():
    # Define LLM configuration
    llm_config = {
        "config_list": [
            {
                "model": os.environ.get('OPENAI_MODEL_NAME'),
                "api_key": os.environ.get("OPENAI_API_KEY"),
            }
        ],
        "temperature": 0,
    }

    # Create agents
    assistant = AssistantAgent(
        name="assistant",
        llm_config=llm_config,
    )

    user_proxy = UserProxyAgent(
        name="user_proxy",
        human_input_mode="NEVER",
        max_consecutive_auto_reply=1,
        is_termination_msg=lambda x: x.get("content", "").rstrip().endswith("TERMINATE"),
        code_execution_config=False,
    )

    # Set custom span, name is root_span
    with tracer.start_as_current_span("root_span") as span:
        span.set_attribute("cozeloop.span_type", "custom")

        # Start the conversation
        user_proxy.initiate_chat(
            assistant,
            message="Explain the concept of 'Retrieval-Augmented Generation' in 2 sentences.",
        )

if __name__ == "__main__":
    main()
