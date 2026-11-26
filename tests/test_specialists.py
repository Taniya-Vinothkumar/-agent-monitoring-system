
"""Tests for independent AI specialist reviewers.

All Ollama requests are mocked. These tests do not require a running server.
"""

import json

import httpx
import pytest

from reviewer.specialists import (
    SPECIALISTS,
    _parse_response,
    run_specialist_reviewers,
)


VALID_RESPONSE = {
    "verdict": "pass",
    "checks": [
        {
            "check_id": "tool_selection",
            "status": "pass",
            "detail": "The selected tool was appropriate.",
        },
        {
            "check_id": "execution_consistency",
            "status": "pass",
            "detail": "The trace is internally consistent.",
        },
    ],
    "summary": "The execution looks correct.",
}


EXECUTION = {
    "execution_id": "exec_test_001",
    "task": "Calculate 10 + 5",
    "status": "completed",
    "steps": [],
    "final_answer": "15",
}

EVIDENCE = {
    "execution_id": "exec_test_001",
    "verifiable_claims": [],
}


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass

    def json(self):
        return {
            "message": {
                "content": self.content,
            }
        }


def test_parse_response_accepts_valid_json():
    parsed = _parse_response(json.dumps(VALID_RESPONSE))

    assert parsed["verdict"] == "pass"
    assert len(parsed["checks"]) == 2


def test_parse_response_rejects_invalid_json():
    with pytest.raises(ValueError):
        _parse_response("not valid json")


def test_parse_response_rejects_invalid_verdict():
    invalid = {
        **VALID_RESPONSE,
        "verdict": "unknown",
    }

    with pytest.raises(ValueError):
        _parse_response(json.dumps(invalid))


def test_both_specialists_return_valid_reviews(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        return FakeResponse(json.dumps(VALID_RESPONSE))

    monkeypatch.setattr(
        "reviewer.specialists.httpx.post",
        fake_post,
    )

    results = run_specialist_reviewers(
        EXECUTION,
        EVIDENCE,
        base_url="http://localhost:11434",
        model="qwen2.5:3b",
        timeout_seconds=10,
    )

    assert len(results) == 2
    assert len(calls) == 2

    assert {r["role"] for r in results} == {
        "tool_use",
        "task_completion",
    }

    for result in results:
        assert result["status"] == "completed"
        assert result["verdict"] == "pass"
        assert result["model"] == "qwen2.5:3b"
        assert result["latency_ms"] >= 0
        assert len(result["checks"]) == 2


def test_timeout_is_handled_without_crashing(monkeypatch):
    def fake_post(url, **kwargs):
        raise httpx.TimeoutException("Test timeout")

    monkeypatch.setattr(
        "reviewer.specialists.httpx.post",
        fake_post,
    )

    results = run_specialist_reviewers(
        EXECUTION,
        EVIDENCE,
        base_url="http://localhost:11434",
        model="qwen2.5:3b",
        timeout_seconds=1,
    )

    assert len(results) == 2

    for result in results:
        assert result["status"] == "timeout"
        assert result["verdict"] == "needs_attention"
        assert result["checks"] == []


def test_connection_error_is_handled_without_crashing(monkeypatch):
    def fake_post(url, **kwargs):
        raise httpx.ConnectError("Ollama unavailable")

    monkeypatch.setattr(
        "reviewer.specialists.httpx.post",
        fake_post,
    )

    results = run_specialist_reviewers(
        EXECUTION,
        EVIDENCE,
        base_url="http://localhost:11434",
        model="qwen2.5:3b",
    )

    assert len(results) == 2

    for result in results:
        assert result["status"] == "unavailable"
        assert result["verdict"] == "needs_attention"


def test_invalid_model_response_is_handled(monkeypatch):
    def fake_post(url, **kwargs):
        return FakeResponse("invalid JSON response")

    monkeypatch.setattr(
        "reviewer.specialists.httpx.post",
        fake_post,
    )

    results = run_specialist_reviewers(
        EXECUTION,
        EVIDENCE,
        base_url="http://localhost:11434",
        model="qwen2.5:3b",
    )

    assert len(results) == 2

    for result in results:
        assert result["status"] == "invalid_response"
        assert result["verdict"] == "needs_attention"


def test_specialist_roles_are_distinct():
    assert SPECIALISTS["tool_use"]["name"] == "tool-use-reviewer"
    assert SPECIALISTS["task_completion"]["name"] == (
        "task-completion-reviewer"
    )
