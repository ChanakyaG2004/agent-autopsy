import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError

from app.assurance import report_answer
from app.agent import execute_agent
from app.ollama_provider import (DEFAULT_MODEL, DEFAULT_URL, OllamaDriver, OllamaUnavailable,
                                 local_endpoint, parse_ollama_usage)
from app.providers import ProviderNotConfigured, make_driver


def response(data, status=200):
    return Mock(status_code=status, json=Mock(return_value=data))


@pytest.fixture
def local_service(monkeypatch):
    client = Mock()
    options = {}
    calls = []

    def metadata(method, url, **kwargs):
        if options.get("offline"):
            raise requests.ConnectionError("private-local-payload")
        if url.endswith("/version"):
            return response({"version": "test-version"})
        if url.endswith("/tags"):
            return response({"models": [] if options.get("not_installed") else [
                {"name": DEFAULT_MODEL, "digest": "a" * 64}]})
        return response({"capabilities": [] if options.get("no_tools") else ["completion", "tools"],
                         "remote_host": "https://cloud.example" if options.get("remote") else None})

    def chat(url, **kwargs):
        body = deepcopy(kwargs["json"])
        calls.append(body)
        if options.get("timeout"):
            raise requests.Timeout("private-local-payload")
        if options.get("status"):
            return response({"error": "private-local-payload"}, options["status"])
        messages = body["messages"]
        results = [json.loads(item["content"]) for item in messages if item["role"] == "tool"]
        denied = results and results[-1].get("error", {}).get("code") == "PERMISSION_DENIED"
        done = results and results[-1].get("refunded_cents") == 4900
        if done or denied:
            message = {"role": "assistant", "content": report_answer(results[-1])}
        else:
            name = "get_order" if not results or "error" in results[-1] else "issue_refund"
            arguments = {"order_id": "order-123"}
            if name == "issue_refund":
                arguments["amount_cents"] = 4900
            message = {"role": "assistant", "content": "", "thinking": "private-thinking-content",
                       "tool_calls": [{"function": {"name": name, "arguments": arguments}}]}
        data = {"model": DEFAULT_MODEL, "done": True, "done_reason": "stop", "message": message,
                "prompt_eval_count": 30, "eval_count": 5}
        data.update(options.get("override", {}))
        return response(data)

    client.request.side_effect = metadata
    client.post.side_effect = chat
    monkeypatch.setattr("app.ollama_provider.requests.Session", lambda: client)
    monkeypatch.setenv("OLLAMA_MODEL", DEFAULT_MODEL)
    monkeypatch.setenv("OLLAMA_BASE_URL", DEFAULT_URL)
    return client, calls, options


@pytest.mark.parametrize("url", ["https://example.com", "http://example.com", "http://127.0.0.1.evil", "https://localhost",
    "http://user:secret@localhost:11434", "http://localhost:11434/path", "http://localhost:11434?key=secret",
    "http://localhost:0", "http://localhost:bad", "http://localhost/#fragment"])
def test_only_http_loopback_origins_are_accepted(url):
    with pytest.raises(OllamaUnavailable) as caught:
        local_endpoint(url)
    assert "secret" not in str(caught.value)


def test_only_final_reporting_disables_tools_and_requests_native_json(local_service):
    client, calls, options = local_service
    driver = OllamaDriver(DEFAULT_MODEL, DEFAULT_URL)
    try:
        result = execute_agent(driver)
        assert result.status == "completed"
        assert calls[0]["tools"] and "format" not in calls[0]
        assert calls[1]["tools"] and "format" not in calls[1]
        assert calls[-1]["tools"] == [] and calls[-1]["format"] == "json"
        assert "Final reporting phase" in calls[-1]["messages"][0]["content"]
        assert driver.model_telemetry.configuration.report_output_format == "json"
        assert driver.model_telemetry.configuration.report_instructions_sha256
    finally:
        driver.close()


@pytest.mark.parametrize("url", [DEFAULT_URL, "http://localhost:11434/", "http://[::1]:11434"])
def test_local_origins_are_valid(url):
    assert local_endpoint(url) == url.rstrip("/")


@pytest.mark.parametrize("option", ["offline", "not_installed", "no_tools", "remote"])
def test_preflight_refuses_missing_or_cloud_backed_models(local_service, option):
    client, calls, options = local_service
    options[option] = True
    with pytest.raises(ProviderNotConfigured) as caught:
        make_driver("ollama")
    assert not calls and client.close.called
    assert "private-local-payload" not in str(caught.value)


def test_cloud_tags_are_rejected_before_any_http_request(local_service):
    client, calls, options = local_service
    with pytest.raises(OllamaUnavailable):
        OllamaDriver("some-model:cloud", DEFAULT_URL)
    assert not client.request.called and not calls


@pytest.mark.parametrize("scenario,count", [("normal", 3), ("timeout_after_commit", 4), ("permission_denied", 3)])
def test_native_tool_loop_replays_feedback_and_measures_only_inference(local_service, scenario, count):
    client, calls, _ = local_service
    driver, model = make_driver("ollama")
    try:
        result = execute_agent(driver, scenario)
        assert result.status == "completed" and model == DEFAULT_MODEL
        assert client.trust_env is False
        assert all(call["stream"] is False and call["options"]["num_ctx"] == 8192 for call in calls)
        assert all(call["messages"][0]["role"] == "system" for call in calls)
        assert calls[1]["messages"][-1]["tool_name"] == "get_order"
        assert len(calls) == count and client.request.call_count == 3
        assert "private-thinking-content" not in json.dumps(calls)
        measured = driver.model_telemetry
        assert measured.provider == "ollama" and measured.telemetry_version == "ollama-chat-v1"
        assert measured.attempted_requests == count and measured.usage_complete
        assert measured.known_usage.total_tokens == 35 * count
        assert measured.known_usage.cached_input_tokens is None
        assert measured.known_usage.reasoning_output_tokens is None
        assert measured.configuration.model_digest == "a" * 64
        assert measured.configuration.server_version == "test-version"
        assert measured.configuration.store is None
        assert "private-thinking-content" not in measured.model_dump_json()
        assert client.post.call_args.kwargs["allow_redirects"] is False
    finally:
        driver.close()


@pytest.mark.parametrize("override", [
    {"done": False}, {"done_reason": "length"},
    {"message": {"role": "system", "content": "wrong role"}},
    {"message": {"role": "assistant", "content": "", "tool_calls": "bad"}},
    {"message": {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "issue_refund", "arguments": "bad"}}]}},
    {"message": {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "shell", "arguments": {}}}]}},
])
def test_bad_responses_cannot_mutate_the_sandbox(local_service, override):
    local_service[2]["override"] = override
    driver = OllamaDriver(DEFAULT_MODEL, DEFAULT_URL)
    try:
        result = execute_agent(driver)
        assert result.status == "failed" and result.initial_state == result.final_state
        assert driver.model_telemetry.attempted_requests == 1
        assert driver.model_telemetry.known_usage.total_tokens == 35
    finally:
        driver.close()


def test_parallel_calls_are_refused_by_the_shared_loop(local_service):
    call = {"function": {"name": "issue_refund", "arguments": {"order_id": "order-123", "amount_cents": 2450}}}
    local_service[2]["override"] = {"message": {"role": "assistant", "content": "", "tool_calls": [call, call]}}
    driver = OllamaDriver(DEFAULT_MODEL, DEFAULT_URL)
    try:
        result = execute_agent(driver)
        assert result.status == "failed" and "multiple" in result.error
        assert result.initial_state == result.final_state
    finally:
        driver.close()


def test_json_text_is_never_promoted_to_a_business_action(local_service):
    local_service[2]["override"] = {"message": {"role": "assistant", "content":
        json.dumps({"name": "issue_refund", "arguments": {"order_id": "order-123", "amount_cents": 4900}})}}
    driver = OllamaDriver(DEFAULT_MODEL, DEFAULT_URL)
    try:
        result = execute_agent(driver)
        assert result.status == "completed" and result.initial_state == result.final_state
        assert [step["kind"] for step in result.steps] == ["answer"]
        from app.evaluation import evaluate_refund
        assert evaluate_refund(result.final_state).verdict == "failed"
    finally:
        driver.close()


@pytest.mark.parametrize("option", ["timeout", "status"])
def test_local_errors_are_measured_without_retry_or_payload_leaks(local_service, option):
    client, calls, options = local_service
    options[option] = 500 if option == "status" else True
    driver = OllamaDriver(DEFAULT_MODEL, DEFAULT_URL)
    try:
        result = execute_agent(driver)
        measured = driver.model_telemetry
        assert result.status == "failed" and len(calls) == 1
        assert measured.attempted_requests == 1 and measured.known_usage is None
        assert not measured.usage_complete and measured.requests[0].outcome == "error"
        assert "private" not in measured.model_dump_json() and "private" not in result.error
    finally:
        driver.close()


@pytest.mark.parametrize("data,status", [({}, "unavailable"), ({"eval_count": 1}, "invalid"),
    ({"prompt_eval_count": True, "eval_count": 1}, "invalid"),
    ({"prompt_eval_count": -1, "eval_count": 1}, "invalid"),
    ({"prompt_eval_count": 0, "eval_count": 0}, "reported")])
def test_native_usage_validation_preserves_unknown_and_zero(data, status):
    assert parse_ollama_usage(data)[0] == status


def test_default_validation_provider_requires_no_key(monkeypatch, capsys):
    from app.validate_model import main
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    assert main([]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["provider"] == "ollama" and not report["key_required"] and not report["executed"]


def test_ollama_api_saves_correct_provider_and_legacy_history_survives(client, local_service, database_connection):
    experiment = client.post("/experiments", json={"name": "Local model", "agent_version": "refund-v1", "scenarios": ["normal"]}).json()
    path = f'/experiments/{experiment["id"]}/runs'
    response_body = client.post(path, json={"mode": "ollama"})
    assert response_body.status_code == 201
    run = response_body.json()
    assert run["mode"] == "ollama" and run["status"] == "completed"
    assert run["evaluation"]["verdict"] == "passed"
    assert run["model_telemetry"]["provider"] == "ollama"
    assert run["model_telemetry"]["configuration"]["model_digest"] == "a" * 64
    assert client.get(path).json()[0] == run
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["connection"] = database_connection
    with pytest.raises(IntegrityError), database_connection.begin_nested():
        command.downgrade(config, "53242250fbfc")
    assert client.get(path).json()[0] == run


def test_unavailable_local_provider_does_not_claim_experiment(client, local_service):
    local_service[2]["offline"] = True
    experiment = client.post("/experiments", json={"name": "Offline local model", "agent_version": "refund-v1", "scenarios": ["normal"]}).json()
    path = f'/experiments/{experiment["id"]}/runs'
    assert client.post(path, json={"mode": "ollama"}).status_code == 503
    assert client.get(path).json() == []
    assert client.get(f'/experiments/{experiment["id"]}').json()["status"] == "draft"


def test_validation_reports_offline_service_without_a_traceback(database_connection, local_service, monkeypatch, capsys):
    from sqlalchemy.orm import Session
    from app import validate_model
    local_service[2]["offline"] = True
    monkeypatch.setattr(validate_model, "Session", lambda *args, **kwargs: Session(
        database_connection, expire_on_commit=False, join_transaction_mode="create_savepoint"))
    assert validate_model.main(["--execute"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert not report["passed"] and report["provider"] == "ollama"
    assert "private" not in str(report)
