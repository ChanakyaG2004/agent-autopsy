import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def valid_draft():
    return {
        "name": "Refund recovery baseline",
        "agent_version": "refund-v1",
        "scenarios": ["normal", "timeout_after_commit"],
    }


def test_validates_and_trims_name(client):
    draft = valid_draft()
    draft["name"] = "  Refund recovery baseline  "
    response = client.post("/experiments/validate", json=draft)
    assert response.status_code == 200
    assert response.json() == {
        "message": 'Configuration "Refund recovery baseline" is valid for 2 scenario(s). Nothing has been saved or run.'
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "    "},
        {"name": "ab"},
        {"name": "x" * 81},
        {"agent_version": "   "},
        {"agent_version": "x" * 81},
        {"scenarios": []},
        {"scenarios": ["unknown"]},
        {"scenarios": ["normal", "normal"]},
        {"unexpected": "value"},
    ],
)
def test_rejects_invalid_configuration(client, changes):
    response = client.post("/experiments/validate", json=valid_draft() | changes)
    assert response.status_code == 422
    assert response.json()["detail"]


def test_requires_agent_version(client):
    draft = valid_draft()
    del draft["agent_version"]
    response = client.post("/experiments/validate", json=draft)
    assert response.status_code == 422


@pytest.mark.parametrize("origin", ["http://localhost:3000", "http://127.0.0.1:3000"])
def test_allows_local_browser_preflight(client, origin):
    response = client.options(
        "/experiments/validate",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_rejects_unlisted_browser_origin(client):
    response = client.options(
        "/experiments/validate",
        headers={
            "Origin": "https://unlisted.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
