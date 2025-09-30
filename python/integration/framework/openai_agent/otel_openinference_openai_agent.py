import asyncio

import time
import os

# Preserve original environment variable configuration
os.environ['OPENAI_BASE_URL'] = 'https://ark.cn-beijing.volces.com/api/v3' # use ark model url by default, from https://www.volcengine.com/docs/82379/1361424
os.environ['OPENAI_API_KEY'] = '***'  # your api key
os.environ['OPENAI_MODEL_NAME'] = '***' # your model name, like doubao-1-5-vision-pro-32k-250115

from agents._config import set_default_openai_api
from agents import Agent, Runner, function_tool
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor

set_default_openai_api("chat_completions") # use chat_completions by default, not responses

endpoint = "https://api.coze.cn/v1/loop/opentelemetry/v1/traces" # cozeloop otel endpoint
tracer_provider = TracerProvider()
tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
    endpoint=endpoint,
    headers={
        "cozeloop-workspace-id": "***", # cozeloop workspace id
        "Authorization": "Bearer ***", # cozeloop pat or sat token
    }
)))

tracer = tracer_provider.get_tracer(__name__)

OpenAIAgentsInstrumentor().instrument(tracer_provider=tracer_provider)


@function_tool
def get_weather(city: str) -> str:
    return f"The weather in {city} is sunny."


async def test():
    spanish_agent = Agent(
        name="Spanish agent",
        instructions="You only speak Spanish.",
        model=os.environ["OPENAI_MODEL_NAME"],
    )

    english_agent = Agent(
        name="English agent",
        instructions="You only speak English",
        model=os.environ["OPENAI_MODEL_NAME"],
        tools=[get_weather],
    )

    chinese_agent = Agent(
        name="Chinese agent",
        instructions="You only speak Chinese",
        model=os.environ["OPENAI_MODEL_NAME"],
    )

    triage_agent = Agent(
        name="Triage agent",
        instructions="Handoff to the appropriate agent based on the language of the request.",
        handoffs=[spanish_agent, english_agent, chinese_agent],
        model=os.environ["OPENAI_MODEL_NAME"],
    )

    # set custom span
    with tracer.start_as_current_span("root_span") as span:
        span.set_attribute("cozeloop.span_type", "custom")

        # start openai agent runner
        result = await Runner.run(triage_agent, input="What's the weather in Shanghai?")
        print(result.final_output)


async def main():
    loop = asyncio.get_running_loop()
    await loop.create_task(test())
    time.sleep(2)


asyncio.run(main())