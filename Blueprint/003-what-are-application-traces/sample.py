import time
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor, ConsoleSpanExporter,
)

# Setup: print spans to the console (ConsoleSpanExporter)
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("shop-app")

def load_user():
    with tracer.start_as_current_span("load_user"):
        time.sleep(0.8)  # pretend this is a slow database query

def charge_card():
    with tracer.start_as_current_span("charge_card"):
        time.sleep(0.2)

def buy():
    with tracer.start_as_current_span("buy_request") as span:
        span.set_attribute("user.id", 42)
        load_user()
        charge_card()

buy()