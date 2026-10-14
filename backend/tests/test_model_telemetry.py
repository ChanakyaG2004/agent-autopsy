import json
from copy import deepcopy
from uuid import uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from openai import OpenAI as RealOpenAI
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent import execute_agent
from app.model_telemetry import parse_usage
from app.models import AgentRun, Experiment
from app.providers import OpenAIDriver
from app.tools import RefundSandbox


USAGE = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120,
         "input_tokens_details": {"cached_tokens": 25, "cache_write_tokens": 10},
         "output_tokens_details": {"reasoning_tokens": 5}}


@pytest.fixture
def simulated_provider(monkeypatch):
    """Use the installed SDK and HTTP serialization, with no real network requests."""
    calls = []
    options = {}

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        index = len(calls)
        if options.get("timeout_at") == index:
            raise httpx.ReadTimeout("private-provider-payload", request=request)
        if options.get("http_status"):
            return httpx.Response(options["http_status"], json={"error": {"message": "private diagnostic", "type": "test_error"}})
        results = [json.loads(item["output"]) for item in body["input"]
                   if item.get("type") == "function_call_output"]
        denied = results and results[-1].get("error", {}).get("code") == "PERMISSION_DENIED"
        done = results and results[-1].get("refunded_cents") == 4900
        if denied or done:
            output = [{"type": "message", "id": f"msg-{index}", "role": "assistant", "status": "completed",
                       "content": [{"type": "output_text", "text": "Refund denied." if denied else "Refund verified.", "annotations": []}]}]
        else:
            name = "get_order" if not results or "error" in results[-1] else "issue_refund"
            arguments = {"order_id": "order-123"}
            if name == "issue_refund":
                arguments["amount_cents"] = 4900
            output = [{"type": "function_call", "id": f"fc-{index}", "call_id": f"call-{index}",
                       "name": name, "arguments": json.dumps(arguments)}]
        usage = None if options.get("missing_usage_at") == index else deepcopy(USAGE)
        return httpx.Response(200, json={
            "id": f"resp-{index}", "object": "response", "created_at": 1,
            "model": "reported-model-snapshot", "status": options.get("status", "completed"),
            "output": output, "usage": usage,
        })

    def factory(**kwargs):
        return RealOpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    monkeypatch.setattr("app.providers.OpenAI", factory)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-never-persist")
    monkeypatch.setenv("OPENAI_MODEL", "requested-model-alias")
    return calls, options


@pytest.mark.parametrize("raw,status", [
    (None, "unavailable"), ({}, "invalid"),
    (USAGE | {"input_tokens": True}, "invalid"),
    (USAGE | {"output_tokens": -1}, "invalid"),
    (USAGE | {"total_tokens": 121}, "invalid"),
    (USAGE | {"input_tokens_details": {"cached_tokens": 101}}, "invalid"),
    (USAGE | {"output_tokens_details": {"reasoning_tokens": 21}}, "invalid"),
    (USAGE, "reported"),
    ({"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}, "reported"),
])
def test_usage_validation_distinguishes_missing_invalid_and_reported_zero(raw, status):
    actual, usage = parse_usage(raw)
    assert actual == status
    assert (usage is not None) == (status == "reported")


def test_missing_breakdowns_stay_unknown_and_extra_fields_are_not_saved():
    _, usage = parse_usage({"input_tokens": 1, "output_tokens": 2, "total_tokens": 3,
                            "secret": "private-provider-payload"})
    assert usage.cached_input_tokens is None and usage.reasoning_output_tokens is None
    assert "private" not in usage.model_dump_json()


def test_installed_sdk_captures_each_response_and_sums_without_double_counting(simulated_provider, monkeypatch):
    ticks = iter([100_000_000, 102_500_000, 200_000_000, 202_500_000, 300_000_000, 302_500_000])
    monkeypatch.setattr("app.providers.perf_counter_ns", lambda: next(ticks))
    driver = OpenAIDriver("test-key", "requested-model-alias")
    try:
        result = execute_agent(driver)
        measured = driver.model_telemetry
        assert result.status == "completed"
        assert measured.attempted_requests == measured.reported_usage_requests == 3
        assert measured.usage_complete
        assert measured.configuration.max_output_tokens == 1024
        assert measured.configuration.max_turns == 6 and measured.configuration.max_retries == 0
        assert len(measured.configuration.instructions_sha256) == 64
        assert measured.total_request_duration_ms == 7.5
        assert measured.known_usage.model_dump() == dict(input_tokens=300, output_tokens=60,
            total_tokens=360, cached_input_tokens=75, cache_write_input_tokens=30, reasoning_output_tokens=15)
        assert [request.sequence for request in measured.requests] == [1, 2, 3]
        assert all(request.requested_model == "requested-model-alias" and
                   request.reported_model == "reported-model-snapshot" for request in measured.requests)
        calls, _ = simulated_provider
        assert all(call["store"] is False and call["parallel_tool_calls"] is False for call in calls)
        assert "test-key" not in measured.model_dump_json()
    finally:
        driver.close()


def test_partial_usage_is_an_explicit_known_subtotal(simulated_provider):
    _, options = simulated_provider
    options["missing_usage_at"] = 2
    driver = OpenAIDriver("test-key", "model")
    try:
        assert execute_agent(driver).status == "completed"
        measured = driver.model_telemetry
        assert measured.attempted_requests == 3 and measured.reported_usage_requests == 2
        assert not measured.usage_complete and measured.known_usage.total_tokens == 240
        assert measured.requests[1].usage is None and measured.requests[1].usage_status == "unavailable"
    finally:
        driver.close()


def test_incomplete_response_usage_is_retained_before_tool_execution(simulated_provider):
    _, options = simulated_provider
    options["status"] = "incomplete"
    driver = OpenAIDriver("test-key", "model")
    try:
        result = execute_agent(driver)
        assert result.status == "failed" and result.steps == []
        assert driver.model_telemetry.known_usage.total_tokens == 120
        assert driver.model_telemetry.requests[0].response_status == "incomplete"
    finally:
        driver.close()


@pytest.mark.parametrize("status,error", [(401, "authentication"), (403, "permission"), (429, "rate_limit"), (500, "api_error")])
def test_http_error_measurements_do_not_retry_or_leak_payloads(simulated_provider, status, error):
    calls, options = simulated_provider
    options["http_status"] = status
    driver = OpenAIDriver("test-key", "model")
    try:
        result = execute_agent(driver)
        measured = driver.model_telemetry
        assert result.status == "failed" and len(calls) == 1
        assert measured.attempted_requests == 1 and measured.known_usage is None
        assert measured.requests[0].error_type == error
        assert measured.requests[0].outcome == "error" and measured.requests[0].response_status is None
        assert not measured.usage_complete
        assert "private" not in measured.model_dump_json() and "private" not in result.error
    finally:
        driver.close()


def test_empty_driver_is_not_reported_as_complete_usage(simulated_provider):
    driver = OpenAIDriver("test-key", "model")
    try:
        assert driver.model_telemetry.attempted_requests == 0
        assert driver.model_telemetry.known_usage is None and not driver.model_telemetry.usage_complete
    finally:
        driver.close()


@pytest.mark.parametrize("scenario,requests,ledger", [("normal", 3, "passed"), ("timeout_after_commit", 4, "passed"), ("permission_denied", 3, "failed")])
def test_api_persists_provider_usage_with_independent_evaluations(client, simulated_provider, scenario, requests, ledger):
    experiment = client.post("/experiments", json={"name": "Model measurement", "agent_version": "refund-v1", "scenarios": [scenario]}).json()
    path = f'/experiments/{experiment["id"]}/runs'
    assert client.post(path, json={"mode": "openai", "model_telemetry": {"total_tokens": 0}}).status_code == 422
    response = client.post(path, json={"mode": "openai"})
    assert response.status_code == 201
    run = response.json()
    assert run["status"] == "completed" and run["evaluation"]["verdict"] == ledger
    assert run["model_name"] == "requested-model-alias"
    measured = run["model_telemetry"]
    assert measured["attempted_requests"] == requests and measured["usage_complete"]
    assert measured["known_usage"]["total_tokens"] == 120 * requests
    assert "test-key-never-persist" not in str(run)
    assert client.get(path).json()[0] == run


def test_timeout_after_refund_preserves_state_and_partial_usage(client, simulated_provider):
    calls, options = simulated_provider
    options["timeout_at"] = 3
    experiment = client.post("/experiments", json={"name": "Provider timeout", "agent_version": "refund-v1", "scenarios": ["normal"]}).json()
    run = client.post(f'/experiments/{experiment["id"]}/runs', json={"mode": "openai"}).json()
    assert run["status"] == "failed" and run["evaluation"]["verdict"] == "passed"
    assert run["final_state"]["refunded_cents"] == 4900 and len(calls) == 3
    measured = run["model_telemetry"]
    assert measured["attempted_requests"] == 3 and measured["reported_usage_requests"] == 2
    assert not measured["usage_complete"] and measured["known_usage"]["total_tokens"] == 240
    assert measured["requests"][-1]["error_type"] == "timeout"
    assert "private" not in str(run)


def test_scripted_runs_remain_unmeasured(client):
    experiment = client.post("/experiments", json={"name": "Scripted measurement", "agent_version": "refund-v1", "scenarios": ["normal"]}).json()
    run = client.post(f'/experiments/{experiment["id"]}/runs', json={"mode": "demo"}).json()
    assert run["model_telemetry"] is None


@pytest.mark.parametrize("error", [False, True])
def test_phoenix_receives_allowlisted_model_usage_and_keeps_unknown_tokens_absent(client, simulated_provider, monkeypatch, error):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.trace import StatusCode
    from app import telemetry
    exporter = InMemorySpanExporter()
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry, "_provider", provider)
    if error:
        simulated_provider[1]["http_status"] = 429
    try:
        experiment = client.post("/experiments", json={"name": "Usage trace", "agent_version": "refund-v1", "scenarios": ["normal"]}).json()
        run = client.post(f'/experiments/{experiment["id"]}/runs', json={"mode": "openai"}).json()
        spans = exporter.get_finished_spans()
        requests = [item for item in spans if item.name == "openai.responses"]
        assert len(requests) == (1 if error else 3)
        root = next(item for item in spans if item.name == "agent.run")
        assert root.attributes["agent.model_requests"] == len(requests)
        assert root.attributes["agent.usage_complete"] is (not error)
        assert "llm.token_count.total" not in root.attributes  # Avoid counting usage twice.
        for request in requests:
            assert request.attributes["openinference.span.kind"] == "LLM"
            assert request.attributes["agent.request_duration_ms"] >= 0
            assert request.attributes["llm.provider"] == "openai"
            if error:
                assert request.status.status_code == StatusCode.ERROR
                assert request.attributes["agent.provider_error"] == "rate_limit"
                assert "llm.token_count.total" not in request.attributes
            else:
                assert request.attributes["llm.model_name"] == "reported-model-snapshot"
                assert request.attributes["agent.requested_model"] == "requested-model-alias"
                assert request.attributes["llm.token_count.prompt"] == 100
                assert request.attributes["llm.token_count.completion"] == 20
                assert request.attributes["llm.token_count.total"] == 120
                assert request.attributes["llm.token_count.prompt_details.cache_read"] == 25
                assert request.attributes["llm.token_count.completion_details.reasoning"] == 5
        assert "private" not in str([dict(item.attributes) for item in spans])
        assert run["trace_id"] == f"{root.context.trace_id:032x}"
    finally:
        provider.shutdown()


def test_telemetry_collector_failure_does_not_erase_execution(client, monkeypatch):
    from app.agent import DemoDriver
    class BrokenMeasurement(DemoDriver):
        @property
        def model_telemetry(self):
            raise RuntimeError("private diagnostic")
    monkeypatch.setattr("app.execution.make_driver", lambda mode: (BrokenMeasurement(), "test-model"))
    experiment = client.post("/experiments", json={"name": "Metrics outage", "agent_version": "refund-v1", "scenarios": ["normal"]}).json()
    run = client.post(f'/experiments/{experiment["id"]}/runs', json={"mode": "openai"}).json()
    assert run["status"] == "completed" and run["evaluation"]["verdict"] == "passed"
    assert run["model_telemetry"] is None and "private" not in str(run)


def test_validation_preflight_never_opens_a_database_or_calls_the_model(monkeypatch, capsys):
    from app import validate_model
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    def forbidden(*args, **kwargs):
        raise AssertionError("Preflight must not execute")
    monkeypatch.setattr(validate_model, "Session", forbidden)
    assert validate_model.main([]) == 2
    report = json.loads(capsys.readouterr().out)
    assert not report["executed"] and not report["ready"]
    assert validate_model.main(["--execute"]) == 2
    assert not json.loads(capsys.readouterr().out)["executed"]
    monkeypatch.setenv("OPENAI_API_KEY", "secret-only-in-environment")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    assert validate_model.main([]) == 0
    output = capsys.readouterr().out
    assert json.loads(output)["ready"] and "secret-only" not in output


@pytest.mark.parametrize("scenario", ["normal", "timeout_after_commit", "permission_denied"])
def test_explicit_validation_command_uses_the_existing_runner(database_connection, simulated_provider, monkeypatch, capsys, scenario):
    from app import validate_model
    monkeypatch.setattr(validate_model, "Session", lambda *args, **kwargs: Session(
        database_connection, expire_on_commit=False, join_transaction_mode="create_savepoint"))
    assert validate_model.main(["--execute", "--scenario", scenario]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["passed"] and all(report["checks"].values())
    assert report["scenario"] == scenario
    assert report["model_telemetry"]["usage_complete"]
    assert "test-key-never-persist" not in str(report)


def test_validation_does_not_pass_when_provider_usage_is_missing(database_connection, simulated_provider, monkeypatch, capsys):
    from app import validate_model
    simulated_provider[1]["missing_usage_at"] = 1
    monkeypatch.setattr(validate_model, "Session", lambda *args, **kwargs: Session(
        database_connection, expire_on_commit=False, join_transaction_mode="create_savepoint"))
    assert validate_model.main(["--execute"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert not report["passed"] and not report["checks"]["usage_available_for_every_attempt"]
    assert report["execution_status"] == "completed" and report["ledger_verdict"] == "passed"


def test_downgrade_protects_saved_measurements(client, simulated_provider, database_connection):
    experiment = client.post("/experiments", json={"name": "Measured history", "agent_version": "refund-v1", "scenarios": ["normal"]}).json()
    path = f'/experiments/{experiment["id"]}/runs'
    run = client.post(path, json={"mode": "openai"}).json()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["connection"] = database_connection
    with pytest.raises(IntegrityError), database_connection.begin_nested():
        command.downgrade(config, "cf13a9502ab7")
    assert database_connection.scalar(text("SELECT version_num FROM alembic_version")) == ScriptDirectory.from_config(config).get_current_head()
    assert client.get(path).json()[0] == run


@pytest.mark.parametrize("mode,measurement", [("demo", {}), ("openai", 0), ("openai", [])])
def test_database_rejects_fake_or_scalar_model_measurements(database_connection, mode, measurement):
    with Session(database_connection, join_transaction_mode="create_savepoint") as session:
        with pytest.raises(IntegrityError), session.begin():
            experiment = Experiment(name="Invalid measurements", agent_version="refund-v1", scenarios=["normal"])
            session.add(experiment)
            session.flush()
            state = RefundSandbox().snapshot()
            session.add(AgentRun(id=uuid4(), experiment_id=experiment.id, mode=mode, status="completed",
                                 task="Refund", initial_state=state, final_state=state, model_telemetry=measurement))
            session.flush()
