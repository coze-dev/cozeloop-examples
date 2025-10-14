import os
import asyncio

os.environ["MODEL_AGENT_API_KEY"] = "***"
os.environ["OBSERVABILITY_OPENTELEMETRY_COZELOOP_SERVICE_NAME"] = "***"
os.environ["OBSERVABILITY_OPENTELEMETRY_COZELOOP_API_KEY"] = "***"

from veadk import Agent, Runner
from veadk.memory.short_term_memory import ShortTermMemory
from veadk.tools.demo_tools import get_city_weather
from veadk.tracing.telemetry.exporters.cozeloop_exporter import CozeloopExporter, CozeloopExporterConfig
from veadk.tracing.telemetry.opentelemetry_tracer import OpentelemetryTracer
from opentelemetry import trace


exporters = [CozeloopExporter(
    config=CozeloopExporterConfig()
)]
tracer = OpentelemetryTracer(exporters=exporters)  # init veadk opentelemetry tracer
otel_raw_tracer = trace.get_tracer_provider().get_tracer(__name__)  # get global opentelemetry tracer for custom span

agent = Agent(
    name="chat_robot",
    description="A robot talk with user.",
    instruction="Talk with user friendly.",
    tools=[get_city_weather],
    tracers=[tracer],
    model_name="doubao-1-5-pro-32k-250115" # use your model name, like doubao-1-5-pro-32k-250115
)

session_id = "session_id"

runner = Runner(
    agent=agent,
    short_term_memory=ShortTermMemory()
)

prompt = "How is the weather like in Beijing? Besides, tell me which tool you invoked."

# set custom span
with otel_raw_tracer.start_as_current_span("root_span") as span:
    span.set_attribute("cozeloop.span_type", "custom")
    # start veadk runner
    asyncio.run(runner.run(messages=prompt, session_id=session_id))
