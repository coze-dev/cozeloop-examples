import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

# Preserve original environment variable configuration
os.environ['OPENAI_BASE_URL'] = '***'
os.environ['OPENAI_API_KEY'] = '***'
os.environ['OPENAI_MODEL_NAME'] = '***' # your model name, like gpt-4o-2024-05-13


os.environ["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] = "https://api.coze.cn/v1/loop/opentelemetry/v1/traces"  # 固定
os.environ[
    "OTEL_EXPORTER_OTLP_HEADERS"] = "cozeloop-workspace-id=***,Authorization=Bearer ***"

otlp_exporter = OTLPSpanExporter(
    timeout=10,
)
trace.set_tracer_provider(TracerProvider())
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(otlp_exporter)
)
tracer = trace.get_tracer(__name__)

# Import and configure the automatic instrumentor from OpenInference
from openinference.instrumentation.llama_index import LlamaIndexInstrumentor

# Initialize LlamaIndex instrumentation
LlamaIndexInstrumentor().instrument()


from workflows import Workflow, step
from workflows.events import (
    Event,
    StartEvent,
    StopEvent,
)

# `pip install llama-index-llms-azure-openai` if you don't already have it, or you can also install llama-index-llms-openai as OpenAI model
from llama_index.llms.azure_openai import AzureOpenAI


class JokeEvent(Event):
    joke: str


class JokeFlow(Workflow):
    llm = AzureOpenAI(
        model=os.environ["OPENAI_MODEL_NAME"],
        azure_endpoint=os.environ["OPENAI_BASE_URL"],
        deployment_name=os.environ["OPENAI_MODEL_NAME"],
    )

    @step
    async def generate_joke(self, ev: StartEvent) -> JokeEvent:
        topic = ev.topic

        prompt = f"Write your best joke about {topic}."
        response = await self.llm.acomplete(prompt)
        return JokeEvent(joke=str(response))

    @step
    async def critique_joke(self, ev: JokeEvent) -> StopEvent:
        joke = ev.joke

        prompt = f"Give a thorough analysis and critique of the following joke: {joke}"
        response = await self.llm.acomplete(prompt)
        return StopEvent(result=str(response))


async def main():
    # set custom span
    with tracer.start_as_current_span("root_span") as span:
        span.set_attribute("cozeloop.span_type", "custom")

        # start workflow
        w = JokeFlow(timeout=60, verbose=False)
        result = await w.run(topic="pirates")
        print(str(result))


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())