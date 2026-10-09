"""Application-owned tracing, with bounded background export to local Phoenix."""

import json
import logging
import os
from contextlib import contextmanager

from openinference.semconv.resource import ResourceAttributes
from openinference.semconv.trace import SpanAttributes
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from requests import Session

logger = logging.getLogger(__name__)
_provider: trace.TracerProvider = trace.NoOpTracerProvider()


def configure_tracing() -> TracerProvider | None:
    """Called once per application lifespan; tests can use an in-memory provider."""
    global _provider
    _provider = trace.NoOpTracerProvider()
    if os.environ.get("AGENT_AUTOPSY_TRACING_ENABLED", "false").lower() != "true":
        return None
    try:
        session = Session()
        session.trust_env = False
        exporter = OTLPSpanExporter(
            endpoint=os.environ.get("PHOENIX_OTLP_ENDPOINT", "http://127.0.0.1:6006/v1/traces"),
            headers={"x-project-name": "agent-autopsy"}, timeout=1.0, session=session,
        )
        provider = TracerProvider(
            resource=Resource({"service.name": "agent-autopsy-api",
                               ResourceAttributes.PROJECT_NAME: "agent-autopsy"}),
            shutdown_on_exit=False,
        )
        provider.add_span_processor(BatchSpanProcessor(
            exporter, max_queue_size=512, max_export_batch_size=64,
            schedule_delay_millis=500, export_timeout_millis=1500,
        ))
        _provider = provider
        return provider
    except Exception as exc:
        logger.error("Tracing setup failed; continuing without export: %s", type(exc).__name__)
        return None


def shutdown_tracing(provider: TracerProvider | None) -> None:
    global _provider
    _provider = trace.NoOpTracerProvider()
    if provider is not None:
        provider.shutdown()


@contextmanager
def span(name: str, kind: str, **attributes):
    """Do not automatically record exception payloads or provider stack traces."""
    tracer = _provider.get_tracer("agent-autopsy")
    with tracer.start_as_current_span(
        name, attributes={SpanAttributes.OPENINFERENCE_SPAN_KIND: kind, **attributes},
        record_exception=False, set_status_on_exception=False,
    ) as current:
        try:
            yield current
        except Exception as exc:
            current.set_attribute("error.type", type(exc).__name__)
            current.set_status(trace.Status(trace.StatusCode.ERROR, "Operation failed"))
            raise
        else:
            # Preserve an explicitly recorded handled error on a normally returning call.
            status = getattr(current, "status", None)
            if status is None or status.status_code != trace.StatusCode.ERROR:
                current.set_status(trace.Status(trace.StatusCode.OK))


def mark_failure(current: trace.Span, message: str) -> None:
    current.set_status(trace.Status(trace.StatusCode.ERROR, message))


def set_json(current: trace.Span, direction: str, value) -> None:
    """Call only with selected application fields, never raw model history."""
    current.set_attribute(f"{direction}.mime_type", "application/json")
    current.set_attribute(f"{direction}.value", json.dumps(value))


def trace_id(current: trace.Span) -> str | None:
    context = current.get_span_context()
    return f"{context.trace_id:032x}" if context.is_valid else None
