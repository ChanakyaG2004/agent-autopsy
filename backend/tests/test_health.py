from unittest.mock import Mock

from sqlalchemy.exc import OperationalError

from app.health import database_ready


def test_live_never_requires_a_database(api_client, monkeypatch):
    def unavailable(_session):
        raise AssertionError("Liveness must not call readiness")
    monkeypatch.setattr("app.main.database_ready", unavailable)
    assert api_client.get("/health/live").json() == {"status": "alive"}


def test_readiness_checks_real_migrated_database(api_client):
    response = api_client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_old_schema_is_not_ready():
    session = Mock()
    session.scalars.return_value = ["old-revision"]
    assert database_ready(session) is False


def test_database_failure_is_unavailable_without_error_disclosure(api_client, monkeypatch):
    session = Mock()
    session.execute.side_effect = OperationalError("secret-host", {}, Exception("secret-password"))
    assert database_ready(session) is False
    session.rollback.assert_called_once()
    monkeypatch.setattr("app.main.database_ready", lambda _: database_ready(session))
    response = api_client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_preflight_does_not_initialize_model_without_explicit_flag(test_engine, monkeypatch, capsys):
    from app import preflight
    monkeypatch.setattr(preflight, "engine", test_engine)
    monkeypatch.setattr("app.ollama_provider.OllamaDriver", lambda *_: (_ for _ in ()).throw(AssertionError("No inference")))
    assert preflight.main([]) == 0
    assert '"inference_requested": false' in capsys.readouterr().out
