from time import sleep

import os

import json
from typing import Any, Dict, List, Optional

import litellm
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, BatchSpanProcessor

from openinference.instrumentation.litellm import LiteLLMInstrumentor

# OpenAI env
os.environ['OPENAI_BASE_URL'] = 'https://ark.cn-beijing.volces.com/api/v3' # use ark model url
os.environ['OPENAI_API_KEY'] = '***' # your ark api key, from https://www.volcengine.com/docs/82379/1361424
os.environ['OPENAI_MODEL_NAME'] = 'openai/doubao-1-5-pro-256k-250115' # your model name, use model provider as prefix, like openai/

# OTEL env
os.environ["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] = "https://api.coze.cn/v1/loop/opentelemetry/v1/traces" # cozeloop otel endpoint
os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = "cozeloop-workspace-id=***,Authorization=Bearer ***" # set your 'spaceID' and 'pat or sat token'

# Set up OpenTelemetry tracing
otlp_exporter = OTLPSpanExporter(
    timeout=10,
)
trace.set_tracer_provider(TracerProvider())
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(otlp_exporter)
)
tracer = trace.get_tracer(__name__)

LiteLLMInstrumentor().instrument()


def get_current_weather(location: str, unit: str = "fahrenheit") -> str:
    with tracer.start_as_current_span("get_current_weather") as span:
        span.set_attribute("cozeloop.span_type", "tool")
        span.set_attribute("cozeloop.input", json.dumps({"location": location, "unit": unit}))

        res = ""
        if "tokyo" in location.lower():
            res = json.dumps({"location": "Tokyo", "temperature": "10", "unit": "celsius"})
        elif "san francisco" in location.lower():
            res = json.dumps({"location": "San Francisco", "temperature": "72", "unit": "fahrenheit"})
        elif "paris" in location.lower():
            res = json.dumps({"location": "Paris", "temperature": "22", "unit": "celsius"})
        else:
            res = json.dumps({"location": location, "temperature": "unknown"})
        span.set_attribute("cozeloop.output", res)

    return res


def to_dict_message(msg: Any) -> Dict[str, Any]:
    return {
        "role": str(getattr(msg, "role", "")),
        "content": str(getattr(msg, "content", "")),
    }


def parallel_function_call() -> None:
    try:
        messages: List[Dict[str, Any]] = [
            {
                "role": "user",
                "content": "What's the weather like in San Francisco, Tokyo, and Paris?",
            }
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_current_weather",
                    "description": "Get the current weather in a given location",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": "The city and state, e.g. San Francisco, CA",
                            },
                            "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                        },
                        "required": ["location"],
                    },
                },
            }
        ]
        response: Any = litellm.completion(
            base_url=os.environ["OPENAI_BASE_URL"],
            api_key=os.environ["OPENAI_API_KEY"],
            model=os.environ["OPENAI_MODEL_NAME"],
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )
        print("\nFirst LLM Response:\n", response)
        response_message: Any = response.choices[0].message
        tool_calls: Optional[Any] = getattr(response_message, "tool_calls", None)

        print("\nLength of tool calls", len(list(tool_calls or [])))

        if tool_calls:
            available_functions = {
                "get_current_weather": get_current_weather,
            }
            messages.append(response_message)
            for tool_call in list(tool_calls):
                function_name = getattr(getattr(tool_call, "function", None), "name", None)
                if function_name is None:
                    continue
                function_to_call = available_functions[function_name]
                function_args = json.loads(
                    getattr(getattr(tool_call, "function", None), "arguments", "{}")
                )
                function_response = function_to_call(
                    location=function_args.get("location"),
                    unit=function_args.get("unit"),
                )
                messages.append(
                    {
                        "tool_call_id": getattr(tool_call, "id", ""),
                        "role": "tool",
                        "name": function_name,
                        "content": function_response,
                    }
                )
            second_response: Any = litellm.completion(
                base_url=os.environ["OPENAI_BASE_URL"],
                api_key=os.environ["OPENAI_API_KEY"],
                model=os.environ["OPENAI_MODEL_NAME"],
                messages=messages,
            )
            print("\nSecond LLM response:\n", second_response)
    except Exception as e:
        print(f"Error occurred: {e}")


if __name__ == "__main__":
    # set custom span, name is root_span
    with tracer.start_as_current_span("root_span") as span:
        span.set_attribute("cozeloop.span_type", "custom")

        # start call
        parallel_function_call()