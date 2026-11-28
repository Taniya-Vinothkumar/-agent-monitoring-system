import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from backend.app.agent.guardian_adapter import (
    GuardianAgentAdapter,
    canonical_config_hash,
    validate_agent_config,
)
from backend.app.agent.tools import (
    TOOL_CHECKERS,
    TOOL_FUNCTIONS,
    business_database_query,
    calculator_date,
    check_business_database_query,
    check_calculator_date,
    check_notes_memory,
    check_policy_document_search,
    check_protected_record_access,
    check_text_extraction,
    notes_memory,
    policy_document_search,
    protected_record_access,
    text_extraction,
)
from backend.app.agent.trace_compat import legacy_trace_to_v1, v1_trace_to_legacy
from backend.app.agent.ollama_executor import OllamaAgentExecutor
from backend.app.agent.task_handler import ToolError
from backend.app.config import Settings, get_settings


def _settings(**overrides):
    values = {"persist_json_files": False, **overrides}
    return Settings(_env_file=None, **values)


def _candidate(adapter, match="colors of apple", tool="policy_document_search"):
    config = copy.deepcopy(adapter.get_config())
    config["tool_routing_rules"].append(
        {
            "rule_id": "test-route",
            "task_match": match,
            "tool_name": tool,
            "priority": 200,
        }
    )
    config["config_version"] = "1.0.1"
    config["parent_version"] = adapter.get_config()["config_version"]
    config["content_hash"] = canonical_config_hash(config)
    return config


def test_external_config_matches_frozen_schema_and_canonical_hash():
    path = Path(__file__).resolve().parents[1] / "backend" / "app" / "agent" / "config" / "guardian_agent_v1.json"
    schema_path = Path(__file__).resolve().parents[1] / "shared" / "schemas" / "agent_config.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert list(Draft202012Validator(schema).iter_errors(config)) == []
    assert config["content_hash"] == canonical_config_hash(config)

    config["instructions"] += " changed"
    with pytest.raises(ValueError, match="content_hash"):
        validate_agent_config(config)


def test_candidate_config_does_not_activate_until_new_adapter_is_created():
    adapter = GuardianAgentAdapter(_settings())
    candidate = _candidate(adapter)

    returned = adapter.apply_config(candidate)
    assert returned["config_version"] == "1.0.1"
    assert adapter.get_config()["config_version"] == "1.0.0"
    before = adapter.run_task({"text": "What are the colors of apple?"})
    assert before["steps"][-1]["outputs"]["verification_status"] == "unverified"

    configured_adapter = GuardianAgentAdapter(_settings(), config=returned)
    after = configured_adapter.run_task({"text": "What are the colors of apple?"})
    assert after["steps"][1]["tool_name"] == "policy_document_search"
    assert after["status"] == "completed"


def test_unsupported_ollama_task_does_not_ask_model_to_invent_a_tool(monkeypatch):
    def unexpected_call(*args, **kwargs):
        raise AssertionError("Unsupported requests must not be sent to Ollama.")

    monkeypatch.setattr(OllamaAgentExecutor, "request_guardian_plan", unexpected_call)
    adapter = GuardianAgentAdapter(_settings(agent_mode="ollama"))

    trace = adapter.run_task({"text": "What are the colors of apple?"})

    assert trace["final_answer"].startswith("UNVERIFIED:")
    assert trace["steps"][0]["outputs"]["verification_status"] == "unverified"


def test_ollama_planning_failure_is_recorded_as_failed_trace(monkeypatch):
    def fail_planning(*args, **kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(OllamaAgentExecutor, "request_guardian_plan", fail_planning)
    adapter = GuardianAgentAdapter(_settings(agent_mode="ollama"))

    trace = adapter.run_task({"text": "Show active customers in Quebec"})

    assert trace["status"] == "failed"
    assert trace["steps"][0]["status"] == "error"
    assert "model unavailable" in trace["steps"][0]["error"]


def test_ollama_uses_complete_deterministic_plans_without_model_call(monkeypatch):
    def unexpected_call(*args, **kwargs):
        raise AssertionError("Complete deterministic plans must bypass Ollama.")

    monkeypatch.setattr(OllamaAgentExecutor, "request_guardian_plan", unexpected_call)
    adapter = GuardianAgentAdapter(_settings(agent_mode="ollama"))
    tasks = [
        "List customer records",
        "Show active customers",
        "Find the travel policy",
        "What is 4 * 3?",
        "Extract email from: avery@example.com",
        "Find a note about customer review",
        "Open protected record PR-1001",
    ]

    for task in tasks:
        trace = adapter.run_task({"text": task})
        assert trace["status"] == "completed", task
        assert any(step["kind"] == "tool_call" for step in trace["steps"]), task
        if task == "Show active customers":
            tool_step = next(step for step in trace["steps"] if step["kind"] == "tool_call")
            assert tool_step["inputs"]["filters"] == {"status": "active"}


def test_ollama_protected_record_access_uses_only_trusted_authorization_context(
    monkeypatch,
):
    def unexpected_call(*args, **kwargs):
        raise AssertionError("A complete protected-record request is deterministic.")

    monkeypatch.setattr(OllamaAgentExecutor, "request_guardian_plan", unexpected_call)
    adapter = GuardianAgentAdapter(_settings(agent_mode="ollama"))
    task = {"text": "Open protected record PR-1001"}

    denied = adapter.run_task(task)
    authorized = adapter.run_task(
        task,
        context={"principal": {"roles": ["hr_records_reader"]}},
    )

    denied_output = next(step for step in denied["steps"] if step["kind"] == "tool_call")[
        "outputs"
    ]
    authorized_output = next(
        step for step in authorized["steps"] if step["kind"] == "tool_call"
    )["outputs"]
    assert denied_output == {
        "record_id": "PR-1001",
        "authorized": False,
        "record": None,
    }
    assert authorized_output["authorized"] is True
    assert authorized_output["record"]["record_id"] == "PR-1001"


def test_ollama_database_filter_validation_accepts_only_task_grounded_filters():
    adapter = GuardianAgentAdapter(_settings(agent_mode="ollama"))
    valid_input = {"table": "customers", "filters": {"status": "active"}}
    adapter._validate_semantic_alignment(
        "Show active customers",
        "business_database_query",
        valid_input,
    )

    for filters in ({}, {"status": "inactive"}):
        with pytest.raises(ValueError, match="Database filters"):
            adapter._validate_semantic_alignment(
                "Show active customers",
                "business_database_query",
                {"table": "customers", "filters": filters},
            )

    assert adapter._expected_database_filters(
        "Open invoice I-200",
        "invoices",
    ) == {"invoice_id": "I-200"}


def test_ollama_model_receives_locked_tool_and_rejects_unverifiable_database_filter(
    monkeypatch,
):
    calls = []

    def plan(self, task, agent_config, expected_tool=None):
        calls.append(expected_tool)
        return {
            "tool": "business_database_query",
            "tool_input": {"table": "customers", "filters": {"status": "active"}},
            "rationale": "The request asks for customers in Quebec.",
        }

    monkeypatch.setattr(OllamaAgentExecutor, "request_guardian_plan", plan)
    trace = GuardianAgentAdapter(_settings(agent_mode="ollama")).run_task(
        {"text": "Show active customers in Quebec"}
    )

    assert calls == ["business_database_query"]
    assert trace["status"] == "failed"
    assert "Database filters do not match" in trace["steps"][0]["error"]
    assert not any(step["kind"] == "tool_call" for step in trace["steps"])


@pytest.mark.parametrize(
    "filters",
    [{}, {"status": "inactive"}],
)
def test_ollama_database_plan_rejects_missing_or_wrong_task_filter(monkeypatch, filters):
    def plan(self, task, agent_config, expected_tool=None):
        return {
            "tool": "business_database_query",
            "tool_input": {"table": "customers", "filters": filters},
            "rationale": "A database lookup.",
        }

    monkeypatch.setattr(OllamaAgentExecutor, "request_guardian_plan", plan)
    trace = GuardianAgentAdapter(_settings(agent_mode="ollama")).run_task(
        {"text": "Show active customers in Quebec"}
    )

    assert trace["status"] == "failed"
    assert not any(step["kind"] == "tool_call" for step in trace["steps"])
    assert "Database filters do not match" in trace["steps"][0]["error"]


@pytest.mark.parametrize(
    "tool_input",
    [
        {"text": "Extract email from avery@example.com", "field": "dates"},
        {"text": "wrong source", "field": "emails"},
    ],
)
def test_ollama_text_extraction_rejects_wrong_field_or_source(monkeypatch, tool_input):
    def plan(self, task, agent_config, expected_tool=None):
        return {
            "tool": "text_extraction",
            "tool_input": tool_input,
            "rationale": "Extract the requested value.",
        }

    monkeypatch.setattr(OllamaAgentExecutor, "request_guardian_plan", plan)
    trace = GuardianAgentAdapter(_settings(agent_mode="ollama")).run_task(
        {"text": "Extract email from avery@example.com"}
    )

    assert trace["status"] == "failed"
    assert not any(step["kind"] == "tool_call" for step in trace["steps"])
    assert "Text extraction" in trace["steps"][0]["error"]


def test_ollama_adapter_rejects_a_model_selected_tool_change(monkeypatch):
    def plan(self, task, agent_config, expected_tool=None):
        assert expected_tool == "text_extraction"
        return {
            "tool": "policy_document_search",
            "tool_input": {"query": task, "top_k": 3, "source_ids": []},
            "rationale": "Changed tool.",
        }

    monkeypatch.setattr(OllamaAgentExecutor, "request_guardian_plan", plan)
    trace = GuardianAgentAdapter(_settings(agent_mode="ollama")).run_task(
        {"text": "Extract email from avery@example.com"}
    )

    assert trace["status"] == "failed"
    assert "changed the deterministically selected tool" in trace["steps"][0]["error"]
    assert not any(step["kind"] == "tool_call" for step in trace["steps"])


@pytest.mark.parametrize(
    ("plan", "expected_tool"),
    [
        (
            {
                "tool": "calculator",
                "tool_input": {"operation": "calculate", "expression": "2 + 2"},
            },
            "calculator",
        ),
        (
            {
                "tool": "calculator",
                "tool_input": {
                    "operation": "calculate",
                    "expression": "2 + 2",
                    "unexpected": True,
                },
                "rationale": "Arithmetic.",
            },
            "calculator",
        ),
        (
            {
                "tool": "policy_document_search",
                "tool_input": {"query": "travel", "top_k": 3, "source_ids": []},
                "rationale": "Wrong selected tool.",
            },
            "calculator",
        ),
        (
            {
                "tool": "protected_record_access",
                "tool_input": {"record_id": "PR-1001"},
                "rationale": "Missing purpose.",
            },
            "protected_record_access",
        ),
    ],
)
def test_guardian_ollama_planner_rejects_malformed_or_changed_plans(
    monkeypatch, plan, expected_tool
):
    class Response:
        def raise_for_status(self):
            return None

        @staticmethod
        def json():
            return {"message": {"content": json.dumps(plan)}}

    monkeypatch.setattr(
        "backend.app.agent.ollama_executor.httpx.post",
        lambda *args, **kwargs: Response(),
    )
    adapter = GuardianAgentAdapter(_settings(agent_mode="ollama"))
    executor = OllamaAgentExecutor(adapter.settings)

    with pytest.raises(ValueError):
        executor.request_guardian_plan(
            "What is 2 + 2?",
            dict(adapter.get_config()),
            expected_tool=expected_tool,
        )


def test_exactly_six_tools_and_each_checker_validates_output():
    assert set(TOOL_FUNCTIONS) == set(TOOL_CHECKERS)
    assert len(TOOL_FUNCTIONS) == 6

    db_input = {"table": "customers", "filters": {"status": "active"}}
    db_output = business_database_query(**db_input)
    assert check_business_database_query(db_input, db_output)
    assert not check_business_database_query(db_input, {"table": "customers", "rows": []})

    policy_input = {"query": "travel booking", "top_k": 3, "source_ids": []}
    policy_output = policy_document_search(**policy_input)
    assert check_policy_document_search(policy_input, policy_output)
    assert not check_policy_document_search(policy_input, {"results": []})

    calc_input = {"operation": "add_days", "date": "2026-01-30", "days": 2}
    calc_output = calculator_date("add_days", date="2026-01-30", days=2)
    assert check_calculator_date(calc_input, calc_output)
    assert not check_calculator_date(calc_input, {"result_date": "2026-02-02"})

    text_input = {"text": "Contact avery@example.com on 2026-02-01", "field": "emails"}
    text_output = text_extraction(**text_input)
    assert check_text_extraction(text_input, text_output)
    assert not check_text_extraction(text_input, {"matches": []})

    notes_input = {"query": "customer review"}
    notes_output = notes_memory(**notes_input)
    assert check_notes_memory(notes_input, notes_output)
    assert not check_notes_memory(notes_input, {"notes": []})

    protected_input = {"record_id": "PR-1001", "purpose": "authorized HR review"}
    denied = protected_record_access(**protected_input)
    assert denied["record"] is None
    assert check_protected_record_access(protected_input, denied)
    authorized_context = {"principal": {"roles": ["hr_records_reader"]}}
    granted = protected_record_access(**protected_input, context=authorized_context)
    assert granted["record"]["record_id"] == "PR-1001"
    assert check_protected_record_access(protected_input, granted, authorized_context)
    assert not check_protected_record_access(protected_input, granted)


@pytest.mark.parametrize(
    "task,expected_tool",
    [
        ("List customer records", "business_database_query"),
        ("Find the travel policy", "policy_document_search"),
        ("What is 4 * 3?", "calculator"),
        ("Extract email from: avery@example.com", "text_extraction"),
        ("Find a note about customer review", "notes_memory"),
        ("Open protected record PR-1001", "protected_record_access"),
    ],
)
def test_adapter_executes_each_registered_tool(task, expected_tool):
    trace = GuardianAgentAdapter(_settings()).run_task({"text": task})
    tool_step = next(step for step in trace["steps"] if step["kind"] == "tool_call")

    assert tool_step["tool_name"] == expected_tool
    assert tool_step["status"] == "ok"


def test_protected_record_access_uses_adapter_context():
    trace = GuardianAgentAdapter(_settings()).run_task(
        {"text": "Open protected record PR-1001"},
        context={"principal": {"roles": ["hr_records_reader"]}},
    )
    tool_step = next(step for step in trace["steps"] if step["kind"] == "tool_call")

    assert tool_step["outputs"]["authorized"] is True
    assert tool_step["outputs"]["record"]["record_id"] == "PR-1001"


def test_invalid_tool_inputs_and_unauthorized_record_access_are_rejected():
    with pytest.raises(ValueError):
        business_database_query("customers", {"secret_column": "x"})
    with pytest.raises(ToolError):
        calculator_date("calculate", expression="2 ** 3")
    with pytest.raises(ValueError):
        policy_document_search("")
    with pytest.raises(ValueError):
        text_extraction("text", "arbitrary_regex")
    with pytest.raises(ValueError):
        protected_record_access("PR-1001", "")
    with pytest.raises(ValueError):
        notes_memory("")

    denied = protected_record_access(
        "PR-1001",
        "untrusted request",
        context={"principal": {"roles": ["employee"]}},
    )
    assert denied == {"record_id": "PR-1001", "authorized": False, "record": None}


def test_v1_and_legacy_trace_conversion_preserves_legacy_contract():
    adapter = GuardianAgentAdapter(_settings())
    versioned = adapter.run_task({"text": "What is 6 * 7?"})
    legacy = v1_trace_to_legacy(versioned)
    converted_back = legacy_trace_to_v1(legacy, versioned["config_version"])

    assert converted_back == versioned
    assert "schema_version" not in legacy
    assert "config_version" not in legacy
    assert all("type" in step and "input" in step and "output" in step for step in legacy["steps"])


def test_same_task_and_config_produce_equivalent_trace_content():
    adapter = GuardianAgentAdapter(_settings())
    first = adapter.run_task({"text": "What is 6 * 7?"})
    second = adapter.run_task({"text": "What is 6 * 7?"})

    def semantic_trace(trace):
        return [
            {
                "kind": step["kind"],
                "tool_name": step["tool_name"],
                "inputs": step["inputs"],
                "outputs": step["outputs"],
                "status": step["status"],
                "error": step["error"],
            }
            for step in trace["steps"]
        ]

    assert semantic_trace(first) == semantic_trace(second)
    assert first["final_answer"] == second["final_answer"]


def test_unsupported_task_is_unverified_without_changing_api_or_review_score(client):
    response = client.post("/api/tasks", json={"task": "What are the colors of apple?"})
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"execution_id", "review_id", "status", "verdict", "trust_score"}

    trace = client.get(f"/api/executions/{body['execution_id']}").json()
    assert trace["final_answer"].startswith("UNVERIFIED:")
    assert trace["steps"][0]["output"]["verification_status"] == "unverified"

    review_response = client.get(f"/api/executions/{body['execution_id']}/review")
    assert review_response.status_code == 200
    assert isinstance(review_response.json()["score"], float)


def test_persistence_keeps_legacy_trace_and_writes_v1_sidecar(client, tmp_path):
    settings = _settings(persist_json_files=True, data_dir=tmp_path)
    client.app.dependency_overrides[get_settings] = lambda: settings

    response = client.post("/api/tasks", json={"task": "What is 6 * 7?"})
    execution_id = response.json()["execution_id"]
    legacy = client.get(f"/api/executions/{execution_id}").json()
    versioned_path = tmp_path / "executions_v1" / f"{execution_id}.json"
    versioned = json.loads(versioned_path.read_text(encoding="utf-8"))

    assert response.status_code == 201
    assert "config_version" not in legacy
    assert "schema_version" not in legacy
    assert versioned["config_version"] == "1.0.0"
    assert versioned["schema_version"] == "1.0"


def test_existing_fault_injection_review_behavior_is_preserved(client):
    response = client.post(
        "/api/tasks",
        json={"task": "What is 2 + 2?", "fault_injection": "inconsistent_answer"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["verdict"] == "fail"
    review = client.get(f"/api/executions/{body['execution_id']}/review").json()
    assert "final_answer_matches_tool_results" in {
        check["check_id"] for check in review["checks"] if check["status"] == "fail"
    }
