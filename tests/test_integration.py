"""Backend <-> reviewer integration, API contract, and schema/sample sync."""
import pytest

from backend.app.api.schemas import EvidenceSummary, ExecutionTrace, ReviewerResult
from reviewer.evaluator import evaluate
from reviewer.validation import schema_errors
from tests.conftest import load_sample

# ---- Shared contract: JSON Schema and Pydantic must agree on the samples ----
SAMPLES = [
    ("sample_execution.json", "execution", ExecutionTrace),
    ("sample_execution_faulty.json", "execution", ExecutionTrace),
    ("sample_evidence.json", "evidence", EvidenceSummary),
    ("sample_review.json", "reviewer", ReviewerResult),
    ("sample_review_faulty.json", "reviewer", ReviewerResult),
]


@pytest.mark.parametrize("filename,schema,model", SAMPLES)
def test_sample_validates_against_json_schema_and_pydantic(filename, schema, model):
    data = load_sample(filename)
    assert schema_errors(data, schema) == []
    model.model_validate(data)


def test_pydantic_output_validates_against_json_schema(client):
    execution_id = client.post("/api/tasks", json={"task": "What is 6 * 7?"}).json()["execution_id"]
    assert schema_errors(client.get(f"/api/executions/{execution_id}").json(), "execution") == []
    assert schema_errors(client.get(f"/api/executions/{execution_id}/evidence").json(), "evidence") == []
    assert schema_errors(client.get(f"/api/executions/{execution_id}/review").json(), "reviewer") == []


def test_samples_are_in_sync_with_current_reviewer():
    """If this fails, run: python scripts/generate_samples.py"""
    for exec_file, evid_file, review_file in [
        ("sample_execution.json", "sample_evidence.json", "sample_review.json"),
    ]:
        fresh = evaluate(load_sample(exec_file), load_sample(evid_file))
        stored = load_sample(review_file)
        assert [(c["check_id"], c["status"]) for c in fresh["checks"]] == \
               [(c["check_id"], c["status"]) for c in stored["checks"]]
        assert fresh["verdict"] == stored["verdict"]


# ---- API ----------------------------------------------------------------
def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_submit_then_retrieve(client):
    resp = client.post("/api/tasks", json={"task": "What is (12 + 8) * 3 / 4?"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "completed" and body["verdict"] == "pass" and 0 < body["trust_score"] <= 1

    trace = client.get(f"/api/executions/{body['execution_id']}").json()
    assert [s["type"] for s in trace["steps"]] == ["plan", "tool_call", "final_answer"]

    review = client.get(f"/api/executions/{body['execution_id']}/review").json()
    assert review["review_id"] == body["review_id"] and review["audit"]["passed"]

    listing = client.get("/api/executions").json()
    assert listing[0]["execution_id"] == body["execution_id"]
    assert listing[0]["verdict"] == "pass" and listing[0]["created_at"].endswith(("Z", "+00:00"))


def test_reviewer_catches_injected_faults_end_to_end(client):
    for fault, failing_check in [("wrong_tool_result", "tool_results_independently_verified"),
                                 ("inconsistent_answer", "final_answer_matches_tool_results")]:
        body = client.post("/api/tasks", json={"task": "What is 2 + 2?", "fault_injection": fault}).json()
        assert body["verdict"] == "fail"
        review = client.get(f"/api/executions/{body['execution_id']}/review").json()
        assert {c["check_id"] for c in review["checks"] if c["status"] == "fail"} == {failing_check}
        assert review["improvements"][0]["requires_human_approval"] is True
        assert review["trust"]["score"] <= 0.5 and review["trust"]["critical_failure_cap_applied"]
    listing = client.get("/api/executions").json()
    assert {i["fault_injection"] for i in listing} == {"wrong_tool_result", "inconsistent_answer"}


def test_failed_run_is_reviewed_too(client):
    body = client.post("/api/tasks", json={"task": "Compute 10 / 0"}).json()
    assert body["status"] == "failed" and body["verdict"] == "fail"


def test_validation_and_not_found(client):
    assert client.post("/api/tasks", json={"task": ""}).status_code == 422
    assert client.post("/api/tasks", json={"task": "x", "fault_injection": "nope"}).status_code == 422
    for path in ["", "/evidence", "/review"]:
        assert client.get(f"/api/executions/exec_missing{path}").status_code == 404
