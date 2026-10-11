import json
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from app import telemetry
from app.agent import DemoDriver, ModelTurn, ReconcileDemoDriver, ToolCall, execute_agent
from app.providers import OpenAIDriver


@pytest.fixture
def captured(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry, "_provider", provider)
    try:
        yield exporter
    finally:
        provider.shutdown()


def test_demo_trace_has_one_root_and_no_fake_llm_spans(captured):
    with telemetry.span("agent.run", "AGENT") as root:
        result = execute_agent(DemoDriver())
        expected_trace_id = telemetry.trace_id(root)
    spans = captured.get_finished_spans()
    assert result.status == "completed"
    assert len(spans) == 6
    root_span = next(item for item in spans if item.name == "agent.run")
    assert root_span.parent is None
    assert all(f"{item.context.trace_id:032x}" == expected_trace_id for item in spans)
    assert all(item.parent.span_id == root_span.context.span_id for item in spans if item is not root_span)
    assert not any(item.attributes["openinference.span.kind"] == "LLM" for item in spans)
    assert all(item.status.status_code == StatusCode.OK for item in spans)
    tools = [item for item in spans if item.name == "tool.execute"]
    assert [item.attributes["tool.name"] for item in tools] == ["get_order", "issue_refund"]
    assert json.loads(tools[-1].attributes["input.value"])["amount_cents"] == 4900
    assert json.loads(tools[-1].attributes["output.value"])["refund_count"] == 1


def test_rejected_tool_marks_child_and_handled_root_error(captured):
    driver = Mock()
    driver.decide.return_value = ModelTurn([], [ToolCall("untrusted-secret-tool", {"secret": "hidden"}, "1")])
    with telemetry.span("agent.run", "AGENT") as root:
        result = execute_agent(driver)
        telemetry.mark_failure(root, result.error)
    spans = captured.get_finished_spans()
    assert result.status == "failed"
    tool = next(item for item in spans if item.name == "tool.execute")
    assert tool.status.status_code == StatusCode.ERROR
    assert tool.attributes["tool.name"] == "unregistered"
    assert next(item for item in spans if item.name == "agent.run").status.status_code == StatusCode.ERROR
    serialized = json.dumps([dict(item.attributes) for item in spans])
    assert "hidden" not in serialized and "untrusted-secret-tool" not in serialized


def test_raw_exception_payloads_are_not_recorded(captured):
    driver = Mock()
    driver.decide.side_effect = RuntimeError("private-provider-payload")
    execute_agent(driver)
    spans = captured.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].status.status_code == StatusCode.ERROR
    assert spans[0].events == ()
    assert "private-provider-payload" not in str(spans[0].attributes)
    assert "private-provider-payload" not in spans[0].status.description


def test_optional_model_span_is_nested_and_does_not_copy_history(captured, monkeypatch):
    sdk = Mock()
    monkeypatch.setattr("app.providers.OpenAI", sdk)
    sdk.return_value.responses.create.return_value = SimpleNamespace(
        status="completed", output=[], output_text="Final private answer",
    )
    driver = OpenAIDriver("private-key", "configured-model")
    with telemetry.span("agent.run", "AGENT"):
        execute_agent(driver)
    spans = captured.get_finished_spans()
    llm = next(item for item in spans if item.name == "openai.responses")
    decision = next(item for item in spans if item.name == "agent.decision")
    assert llm.parent.span_id == decision.context.span_id
    assert llm.attributes["openinference.span.kind"] == "LLM"
    assert llm.attributes["llm.model_name"] == "configured-model"
    serialized = str([dict(item.attributes) for item in spans])
    assert "private-key" not in serialized and "Final private answer" not in serialized


def test_background_export_does_not_block_execution_and_catches_failure(monkeypatch):
    entered, release = Event(), Event()
    class FailingExporter(SpanExporter):
        def export(self, spans):
            entered.set()
            assert release.wait(5)
            raise RuntimeError("Collector unavailable")

    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(BatchSpanProcessor(
        FailingExporter(), max_queue_size=16, max_export_batch_size=1, schedule_delay_millis=1,
    ))
    monkeypatch.setattr(telemetry, "_provider", provider)
    try:
        with telemetry.span("agent.run", "AGENT"):
            result = execute_agent(DemoDriver())
        assert entered.wait(5)
        # This result exists while the exporter is still blocked.
        assert not release.is_set()
        assert result.status == "completed" and result.final_state["refunded_cents"] == 4900
    finally:
        release.set()
        provider.shutdown()


def test_disabled_tracing_has_no_trace_id(monkeypatch):
    monkeypatch.setenv("AGENT_AUTOPSY_TRACING_ENABLED", "false")
    assert telemetry.configure_tracing() is None
    with telemetry.span("agent.run", "AGENT") as root:
        assert telemetry.trace_id(root) is None
        assert execute_agent(DemoDriver()).status == "completed"


def test_tracing_configuration_failure_does_not_break_execution(monkeypatch):
    monkeypatch.setenv("AGENT_AUTOPSY_TRACING_ENABLED", "true")
    monkeypatch.setattr(telemetry, "OTLPSpanExporter", Mock(side_effect=ValueError("invalid endpoint")))
    assert telemetry.configure_tracing() is None
    assert execute_agent(DemoDriver()).status == "completed"


def test_recovered_run_keeps_error_on_lost_response_span(captured):
    with telemetry.span("agent.run", "AGENT"):
        result = execute_agent(ReconcileDemoDriver(), scenario="timeout_after_commit")
    spans = captured.get_finished_spans()
    root = next(item for item in spans if item.name == "agent.run")
    tools = [item for item in spans if item.name == "tool.execute"]
    assert result.status == "completed" and root.status.status_code == StatusCode.OK
    assert [item.attributes["tool.name"] for item in tools] == ["get_order", "issue_refund", "get_order"]
    lost = tools[1]
    assert lost.status.status_code == StatusCode.ERROR
    assert lost.attributes["fault.injected"] is True
    assert lost.attributes["fault.type"] == "timeout_after_commit"
    assert json.loads(lost.attributes["input.value"])["amount_cents"] == 4900
    assert "output.value" not in lost.attributes
    assert tools[2].status.status_code == StatusCode.OK
    assert json.loads(tools[2].attributes["output.value"])["refunded_cents"] == 4900
