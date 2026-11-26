"""API tests for evidence-based reviewer authorization."""

import pytest


def _create_source_executions(client, count=10):
    execution_ids = []

    for number in range(1, count + 1):
        response = client.post(
            "/api/tasks",
            json={"task": f"What is {number} + {number + 3}?"},
        )
        assert response.status_code == 201, response.text
        execution_ids.append(response.json()["execution_id"])

    return execution_ids


def test_authorization_rejects_too_few_execution_ids(client):
    response = client.post(
        "/api/reviewer/authorize",
        json={"execution_ids": ["one", "two"]},
    )
    assert response.status_code == 422


def test_authorization_rejects_unknown_execution_ids(client):
    response = client.post(
        "/api/reviewer/authorize",
        json={
            "execution_ids": [
                f"missing-{number}" for number in range(10)
            ]
        },
    )
    assert response.status_code == 422
    assert "Unknown execution IDs" in response.json()["detail"]


def test_authorization_rejects_duplicate_execution_ids(client):
    execution_ids = _create_source_executions(client, 10)
    execution_ids[-1] = execution_ids[0]

    response = client.post(
        "/api/reviewer/authorize",
        json={"execution_ids": execution_ids},
    )
    assert response.status_code == 422
    assert "Duplicate execution IDs" in response.json()["detail"]


def test_authorization_rejects_fault_injected_execution(client):
    execution_ids = _create_source_executions(client, 9)

    response = client.post(
        "/api/tasks",
        json={
            "task": "What is 20 + 22?",
            "fault_injection": "wrong_tool_result",
        },
    )
    assert response.status_code == 201
    execution_ids.append(response.json()["execution_id"])

    response = client.post(
        "/api/reviewer/authorize",
        json={"execution_ids": execution_ids},
    )

    assert response.status_code == 422
    assert "fault-injection" in response.json()["detail"]


def test_authorization_rejects_malformed_evidence(client):
    from backend.app.database.models import ExecutionRecord
    from backend.app.database.connection import get_session

    execution_ids = _create_source_executions(client, 10)

    # Obtain the test database session through the same dependency override
    # used by the API client.
    session_generator = client.app.dependency_overrides[get_session]()
    session = next(session_generator)

    try:
        record = session.get(ExecutionRecord, execution_ids[0])
        record.evidence = {
            **record.evidence,
            "verifiable_claims": [],
        }
        session.commit()
    finally:
        try:
            next(session_generator)
        except StopIteration:
            pass

    response = client.post(
        "/api/reviewer/authorize",
        json={"execution_ids": execution_ids},
    )

    assert response.status_code == 422
    assert "exactly one verifiable arithmetic claim" in response.json()["detail"]


def test_authorization_runs_with_ten_distinct_executions(client):
    execution_ids = _create_source_executions(client, 10)

    response = client.post(
        "/api/reviewer/authorize",
        json={"execution_ids": execution_ids},
    )

    assert response.status_code == 200, response.text

    body = response.json()

    assert body["status"] == "completed"
    assert body["source_execution_count"] == 10
    assert body["unique_source_cases"] == 10
    assert body["canary_summary"]["total_scenarios"] == 60
    assert body["canary_summary"]["repetitions_are_independent"] is False

    assert body["reliability"]["reviewers"]
    assert body["authorization_decisions"]

    expected_decisions = (
        len(body["reliability"]["reviewers"]) * 5
    )
    assert len(body["authorization_decisions"]) == expected_decisions

    for decision in body["authorization_decisions"]:
        assert "reviewer" in decision
        assert "category" in decision
        assert "authorized" in decision
        assert isinstance(decision["authorized"], bool)


def test_authorization_specialists_default_to_disabled(client, monkeypatch):
    from backend.app.services import authorization

    execution_ids = _create_source_executions(client, 10)

    original = authorization.run_canary_suite
    captured = {}

    def spy(*args, **kwargs):
        captured["include_specialists"] = kwargs.get(
            "include_specialists"
        )
        return original(*args, **kwargs)

    monkeypatch.setattr(authorization, "run_canary_suite", spy)

    response = client.post(
        "/api/reviewer/authorize",
        json={"execution_ids": execution_ids},
    )

    assert response.status_code == 200, response.text
    assert captured["include_specialists"] is False


def test_authorization_blocks_ten_ids_with_identical_evidence(client):
    execution_ids = []

    for _ in range(10):
        response = client.post(
            "/api/tasks",
            json={"task": "What is 25 + 17?"},
        )
        assert response.status_code == 201, response.text
        execution_ids.append(response.json()["execution_id"])

    response = client.post(
        "/api/reviewer/authorize",
        json={"execution_ids": execution_ids},
    )

    assert response.status_code == 200, response.text

    body = response.json()

    assert body["source_execution_count"] == 10
    assert body["unique_source_cases"] == 1

    assert body["authorization_decisions"]
    assert all(
        decision["authorized"] is False
        for decision in body["authorization_decisions"]
    )


def test_authorization_rejects_specialists_when_disabled(client):
    execution_ids = _create_source_executions(client, 10)

    response = client.post(
        "/api/reviewer/authorize",
        json={
            "execution_ids": execution_ids,
            "include_specialists": True,
        },
    )

    assert response.status_code == 422
    assert "disabled in backend configuration" in response.json()["detail"]


def test_authorization_limits_specialist_source_executions(client):
    from backend.app.config import Settings, get_settings

    execution_ids = _create_source_executions(client, 11)

    # Enable specialists only inside this test.
    client.app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        persist_json_files=False,
        specialist_reviews_enabled=True,
    )

    response = client.post(
        "/api/reviewer/authorize",
        json={
            "execution_ids": execution_ids,
            "include_specialists": True,
        },
    )

    assert response.status_code == 422
    assert "at most 10 source executions" in response.json()["detail"]
