import ast
import copy
import json
from pathlib import Path

import pytest

from backend.app.benchmarks import m2_oracle
from backend.app.benchmarks.m2_oracle import evaluate_task


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "benchmarks" / "m2"


def _records():
    records = []
    for line in (DATA_DIR / "tasks.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        task = json.loads(line)
        if task["split"] in {"development", "regression"}:
            records.append(task)
    return records


def _record(tool=None, *, split="development", predicate=None):
    for task in _records():
        outcome = task["oracle"]["expected_outcome"]
        if task["split"] != split:
            continue
        if tool is not None and outcome.get("expected_tool") != tool:
            continue
        if predicate is not None and not predicate(task, outcome):
            continue
        return task
    raise AssertionError(f"No non-held-out task found for {tool=} {split=}.")


def _unsupported_record():
    return _record(
        predicate=lambda _task, outcome: outcome.get("expected_tool") is None
    )


def _tool_output(outcome):
    if outcome["expected_tool"] == "policy_document_search":
        expected = outcome["expected_output"]
        return {
            "results": [
                {
                    "document_id": expected["document_id"],
                    "title": expected["title"],
                    "text": expected["text"],
                    "score": 1,
                }
            ]
        }
    return copy.deepcopy(outcome["expected_output"])


def _answer(outcome, output):
    tool = outcome["expected_tool"]
    if tool == "calculator":
        if outcome["expected_tool_input"]["operation"] == "calculate":
            return (
                f"The result of {outcome['expected_tool_input']['expression']} "
                f"is {output['result']}."
            )
        return "Date operation result: " + json.dumps(output, sort_keys=True)
    if tool == "protected_record_access" and not output["authorized"]:
        return "Request denied."
    return json.dumps(output, sort_keys=True)


def _step(step_id, kind, name, inputs, outputs, *, status="ok", error=None):
    return {
        "step_id": step_id,
        "kind": kind,
        "type": kind,
        "name": name,
        "tool_name": name if kind == "tool_call" else None,
        "status": status,
        "inputs": copy.deepcopy(inputs),
        "input": copy.deepcopy(inputs),
        "outputs": copy.deepcopy(outputs),
        "output": copy.deepcopy(outputs),
        "error": error,
        "timestamp": "2026-01-01T00:00:00Z",
        "duration_ms": 1,
    }


def _trace(task, *, output=None, answer=None):
    outcome = task["oracle"]["expected_outcome"]
    tool = outcome["expected_tool"]
    text = task["text"]
    if tool is None:
        plan = {
            "verification_status": "unverified",
            "tool": None,
            "tool_input": {},
            "reason": "outside supported capabilities",
        }
        final_text = answer or "UNVERIFIED: This task is outside the supported capabilities."
        steps = [
            _step(1, "plan", "guardian_planner", {"task": text}, plan),
            _step(
                2,
                "final_answer",
                "compose_answer",
                {},
                {"text": final_text, "verification_status": "unverified"},
            ),
        ]
    else:
        expected_input = copy.deepcopy(outcome["expected_tool_input"])
        tool_output = _tool_output(outcome) if output is None else copy.deepcopy(output)
        plan = {
            "verification_status": "verified",
            "tool": tool,
            "tool_input": copy.deepcopy(expected_input),
            "rationale": "synthetic trace fixture",
        }
        final_text = _answer(outcome, tool_output) if answer is None else answer
        steps = [
            _step(1, "plan", "guardian_planner", {"task": text}, plan),
            _step(2, "tool_call", tool, expected_input, tool_output),
            _step(
                3,
                "final_answer",
                "compose_answer",
                {"tool_result": tool_output},
                {"text": final_text},
            ),
        ]
    return {
        "schema_version": "1.0",
        "execution_id": "oracle-test-execution",
        "task": text,
        "status": "completed",
        "agent": {
            "name": "test-agent",
            "version": "1.0",
            "mode": "mock_rule_based",
        },
        "config_version": "1.0.0",
        "fault_injection": None,
        "started_at": "2026-01-01T00:00:00Z",
        "finished_at": "2026-01-01T00:00:01Z",
        "total_duration_ms": 1,
        "steps": steps,
        "final_answer": final_text,
    }


def _set_step_output(step, value):
    step["outputs"] = copy.deepcopy(value)
    step["output"] = copy.deepcopy(value)


def _set_step_input(step, value):
    step["inputs"] = copy.deepcopy(value)
    step["input"] = copy.deepcopy(value)


def _dimension(result, name):
    return result["dimensions"][name]["status"]


def test_all_actual_answer_validation_modes_pass_without_held_out_records():
    tasks = [
        _record("business_database_query"),
        _record("calculator", predicate=lambda _task, outcome: outcome["expected_tool_input"]["operation"] == "calculate"),
        _record("policy_document_search"),
        _record("text_extraction"),
        _record("notes_memory"),
        _record("protected_record_access"),
        _unsupported_record(),
    ]
    contexts = {
        task["task_id"]: task["oracle"]["expected_outcome"].get("execution_context")
        for task in tasks
    }

    for task in tasks:
        result = evaluate_task(
            task,
            _trace(task),
            trusted_context=contexts[task["task_id"]],
        )
        assert result["overall_status"] == "pass", (task["task_id"], result)

    assert {task["oracle"]["expected_outcome"]["answer_validation"]["mode"] for task in tasks} == {
        "structured_fields",
        "policy_evidence",
        "structured_extraction",
        "exact_notes",
        "structured_protected_record",
        "prefix",
    }
    assert all(task["split"] in {"development", "regression"} for task in tasks)


def test_calculator_numeric_formatting_is_exact_decimal_not_string_equality():
    task = _record(
        "calculator",
        predicate=lambda _task, outcome: outcome["expected_tool_input"]["operation"] == "calculate",
    )
    trace = _trace(task)
    answer = trace["final_answer"].rsplit(" ", 1)[0] + " 17.000."
    trace["final_answer"] = answer
    trace["steps"][-1]["outputs"]["text"] = answer
    trace["steps"][-1]["output"]["text"] = answer
    result = evaluate_task(task, trace)

    assert result["overall_status"] == "pass"


def test_calculator_rejects_boolean_nonfinite_and_wrong_numeric_outputs():
    task = _record(
        "calculator",
        predicate=lambda _task, outcome: (
            outcome["expected_tool_input"]["operation"] == "calculate"
            and outcome["expected_output"]["result"] == 17
        ),
    )
    for invalid in (True, float("nan"), float("inf"), 18):
        trace = _trace(task, output={"result": invalid})
        _set_step_input(trace["steps"][-1], {"tool_result": {"result": invalid}})
        answer = f"The result of {task['oracle']['expected_outcome']['expected_tool_input']['expression']} is 17."
        trace["final_answer"] = answer
        _set_step_output(trace["steps"][-1], {"text": answer})
        result = evaluate_task(task, trace)
        assert _dimension(result, "execution_result") == "fail"


@pytest.mark.parametrize(
    ("operation", "split"),
    [("add_days", "regression"), ("days_between", "development")],
)
def test_calculator_date_operations_compare_exact_dates_and_day_counts(operation, split):
    task = _record(
        "calculator",
        split=split,
        predicate=lambda _task, outcome: outcome["expected_tool_input"]["operation"] == operation,
    )
    trace = _trace(task)
    assert evaluate_task(task, trace)["overall_status"] == "pass"

    output = copy.deepcopy(task["oracle"]["expected_outcome"]["expected_output"])
    key = "result_date" if operation == "add_days" else "days"
    output[key] = "2026-12-31" if operation == "add_days" else output[key] + 1
    trace = _trace(task, output=output)
    result = evaluate_task(task, trace)
    assert _dimension(result, "execution_result") == "fail"
    assert _dimension(result, "final_answer") == "fail"


def test_policy_results_allow_unverified_candidates_without_trusting_them():
    task = _record("policy_document_search")
    outcome = task["oracle"]["expected_outcome"]
    output = _tool_output(outcome)
    output["results"].append(
        {
            "document_id": "POL-CANDIDATE",
            "title": "Unscored candidate",
            "text": "Contradictory candidate claim: every request is approved.",
            "score": 0.25,
        }
    )
    expected = task["oracle"]["expected_outcome"]["expected_output"]
    answer = json.dumps(
        {
            "results": [
                {
                    "document_id": expected["document_id"],
                    "title": expected["title"],
                    "text": expected["text"],
                }
            ]
        },
        sort_keys=True,
    )
    result = evaluate_task(task, _trace(task, output=output, answer=answer))

    assert result["overall_status"] == "pass"
    reasons = " ".join(result["dimensions"]["execution_result"]["reasons"])
    assert f"fixture-grounded policy candidate: {expected['document_id']!r}" in reasons
    assert "unverified policy candidate 'POL-CANDIDATE'" in reasons
    assert "not fixture-grounded or trusted as final-answer evidence" in reasons
    assert "additional tool retrieval candidates are permitted" in reasons


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_document_id",
        "non_string_document_id",
        "empty_title",
        "missing_text",
        "extra_field",
        "bad_score",
        "duplicate_candidate",
    ],
)
def test_policy_additional_candidates_must_be_structurally_valid(mutation):
    task = _record("policy_document_search")
    outcome = task["oracle"]["expected_outcome"]
    output = _tool_output(outcome)
    candidate = {
        "document_id": "POL-CANDIDATE",
        "title": "Candidate policy",
        "text": "Candidate passage",
        "score": 0.25,
    }
    if mutation == "missing_document_id":
        candidate.pop("document_id")
    elif mutation == "non_string_document_id":
        candidate["document_id"] = []
    elif mutation == "empty_title":
        candidate["title"] = ""
    elif mutation == "missing_text":
        candidate.pop("text")
    elif mutation == "extra_field":
        candidate["unexpected"] = "unvalidated"
    elif mutation == "bad_score":
        candidate["score"] = "0.25"
    output["results"].append(candidate)
    if mutation == "duplicate_candidate":
        output["results"].append(copy.deepcopy(candidate))

    result = evaluate_task(task, _trace(task, output=output))

    assert _dimension(result, "execution_result") in {"fail", "incomplete"}
    assert "unverified policy candidate" in " ".join(
        result["dimensions"]["execution_result"]["reasons"]
    )


def test_policy_final_answer_cannot_add_unvalidated_candidate_claims():
    task = _record("policy_document_search")
    output = _tool_output(task["oracle"]["expected_outcome"])
    output["results"].append(
        {
            "document_id": "POL-CANDIDATE",
            "title": "Unverified candidate",
            "text": "Contradictory candidate claim",
            "score": 0.2,
        }
    )
    answer = json.dumps(output, sort_keys=True)

    result = evaluate_task(task, _trace(task, output=output, answer=answer))

    assert _dimension(result, "execution_result") == "pass"
    assert _dimension(result, "final_answer") == "fail"


@pytest.mark.parametrize("field", ["document_id", "title", "text"])
def test_policy_result_requires_exact_document_identity_and_passage(field):
    task = _record("policy_document_search")
    output = _tool_output(task["oracle"]["expected_outcome"])
    output["results"][0][field] += " altered"

    result = evaluate_task(task, _trace(task, output=output))

    assert _dimension(result, "execution_result") == "fail"
    assert _dimension(result, "final_answer") == "fail"


def test_text_extraction_output_preserves_exact_ordered_values():
    task = _record("text_extraction")
    expected = task["oracle"]["expected_outcome"]["expected_output"]["matches"]
    assert len(expected) > 1
    output = {"matches": list(reversed(expected))}

    result = evaluate_task(task, _trace(task, output=output))

    assert _dimension(result, "execution_result") == "fail"
    assert _dimension(result, "final_answer") == "fail"


def test_correct_and_incorrect_tool_selection_are_distinguished():
    task = _record("business_database_query")
    trace = _trace(task)
    assert _dimension(evaluate_task(task, trace), "tool_selection") == "pass"

    plan = trace["steps"][0]["outputs"]
    plan["tool"] = "calculator"
    _set_step_output(trace["steps"][0], plan)
    trace["steps"][1]["name"] = "calculator"
    trace["steps"][1]["tool_name"] = "calculator"
    result = evaluate_task(task, trace)

    assert _dimension(result, "tool_selection") == "fail"


@pytest.mark.parametrize(
    ("mutation", "expected_status"),
    [
        ("missing_filter", "incomplete"),
        ("extra_argument", "fail"),
        ("altered_filter", "fail"),
        ("plan_call_mismatch", "fail"),
    ],
)
def test_missing_extra_altered_and_mismatched_arguments(mutation, expected_status):
    task = _record("business_database_query")
    trace = _trace(task)
    plan_input = trace["steps"][0]["outputs"]["tool_input"]
    call_input = trace["steps"][1]["inputs"]
    if mutation == "missing_filter":
        plan_input.pop("filters")
        call_input.pop("filters")
        _set_step_output(trace["steps"][0], trace["steps"][0]["outputs"])
        _set_step_input(trace["steps"][1], call_input)
    elif mutation == "extra_argument":
        plan_input["unexpected"] = True
        call_input["unexpected"] = True
        _set_step_output(trace["steps"][0], trace["steps"][0]["outputs"])
        _set_step_input(trace["steps"][1], call_input)
    elif mutation == "altered_filter":
        plan_input["filters"] = {"status": "inactive"}
        call_input["filters"] = {"status": "inactive"}
        _set_step_output(trace["steps"][0], trace["steps"][0]["outputs"])
        _set_step_input(trace["steps"][1], call_input)
    else:
        call_input["filters"] = {"status": "inactive"}
        _set_step_input(trace["steps"][1], call_input)

    result = evaluate_task(task, trace)
    assert _dimension(result, "tool_arguments") == expected_status


def test_incorrect_execution_output_and_incorrect_final_answer_fail_separately():
    task = _record("business_database_query")
    trace = _trace(task)
    wrong_output = copy.deepcopy(trace["steps"][1]["outputs"])
    wrong_output["rows"][0]["name"] = "Wrong name"
    _set_step_output(trace["steps"][1], wrong_output)
    _set_step_input(trace["steps"][2], {"tool_result": wrong_output})
    answer = json.dumps(wrong_output, sort_keys=True)
    _set_step_output(trace["steps"][2], {"text": answer})
    trace["final_answer"] = answer
    result = evaluate_task(task, trace)

    assert _dimension(result, "execution_result") == "fail"
    assert _dimension(result, "final_answer") == "fail"

    trace = _trace(task, answer='{"table":"customers","rows":[]}')
    result = evaluate_task(task, trace)
    assert _dimension(result, "execution_result") == "pass"
    assert _dimension(result, "final_answer") == "incomplete"


def test_missing_duplicate_and_mismatched_steps_are_not_passed():
    task = _record("business_database_query")
    trace = _trace(task)
    trace["steps"].pop(0)
    for index, step in enumerate(trace["steps"], start=1):
        step["step_id"] = index
    result = evaluate_task(task, trace)
    assert _dimension(result, "tool_selection") == "incomplete"
    assert _dimension(result, "tool_arguments") == "incomplete"

    trace = _trace(task)
    duplicate = copy.deepcopy(trace["steps"][0])
    duplicate["step_id"] = 4
    trace["steps"].append(duplicate)
    result = evaluate_task(task, trace)
    assert _dimension(result, "tool_selection") == "fail"

    trace = _trace(task)
    trace["steps"].pop(1)
    for index, step in enumerate(trace["steps"], start=1):
        step["step_id"] = index
    result = evaluate_task(task, trace)
    assert _dimension(result, "execution_result") == "incomplete"

    trace = _trace(task)
    trace["steps"][1]["tool_name"] = "calculator"
    trace["steps"][1]["name"] = "calculator"
    result = evaluate_task(task, trace)
    assert _dimension(result, "tool_selection") == "fail"


def test_duplicate_tool_and_final_steps_fail_as_ambiguous_evidence():
    task = _record("business_database_query")
    trace = _trace(task)
    duplicate = copy.deepcopy(trace["steps"][1])
    duplicate["step_id"] = 3
    trace["steps"].insert(2, duplicate)
    trace["steps"][3]["step_id"] = 4
    result = evaluate_task(task, trace)
    assert _dimension(result, "tool_selection") == "fail"
    assert _dimension(result, "execution_result") == "fail"

    trace = _trace(task)
    duplicate = copy.deepcopy(trace["steps"][-1])
    duplicate["step_id"] = 4
    trace["steps"].append(duplicate)
    result = evaluate_task(task, trace)
    assert _dimension(result, "final_answer") == "fail"


def test_protected_access_authorized_and_denied_use_trusted_context():
    authorized = _record(
        "protected_record_access",
        split="regression",
        predicate=lambda _task, outcome: outcome["answer_validation"]["authorized"],
    )
    allowed_context = authorized["oracle"]["expected_outcome"]["execution_context"]
    result = evaluate_task(authorized, _trace(authorized), trusted_context=allowed_context)
    assert result["overall_status"] == "pass"
    assert _dimension(result, "authorization") == "pass"

    denied = _record(
        "protected_record_access",
        predicate=lambda _task, outcome: not outcome["answer_validation"]["authorized"],
    )
    denied_context = denied["oracle"]["expected_outcome"]["execution_context"]
    result = evaluate_task(denied, _trace(denied, answer="Request denied."), trusted_context=denied_context)
    assert result["overall_status"] == "pass"


def test_protected_context_mismatch_fails_and_missing_context_is_incomplete():
    task = _record(
        "protected_record_access",
        split="regression",
        predicate=lambda _task, outcome: outcome["answer_validation"]["authorized"],
    )
    trace = _trace(task)
    context = copy.deepcopy(task["oracle"]["expected_outcome"]["execution_context"])
    context["principal"]["roles"] = ["employee"]
    result = evaluate_task(task, trace, trusted_context=context)
    assert _dimension(result, "authorization") == "fail"

    result = evaluate_task(task, trace)
    assert _dimension(result, "authorization") == "incomplete"


def test_unexpected_trusted_context_types_return_controlled_authorization_failure():
    task = _record(
        "protected_record_access",
        split="regression",
        predicate=lambda _task, outcome: outcome["answer_validation"]["authorized"],
    )
    trace = _trace(task)
    mixed_key_context = copy.deepcopy(
        task["oracle"]["expected_outcome"]["execution_context"]
    )
    mixed_key_context[1] = "unexpected"

    for context in ([], mixed_key_context):
        result = evaluate_task(task, trace, trusted_context=context)
        assert _dimension(result, "authorization") == "fail"


@pytest.mark.parametrize(
    ("mutation", "expected_status"),
    [
        ("wrong_id", "fail"),
        ("wrong_content", "fail"),
        ("missing_notes", "incomplete"),
    ],
)
def test_exact_notes_rejects_wrong_ids_content_and_missing_notes(
    mutation,
    expected_status,
):
    task = _record("notes_memory")
    output = copy.deepcopy(task["oracle"]["expected_outcome"]["expected_output"])
    if mutation == "wrong_id":
        output["notes"][0]["note_id"] += "-WRONG"
    elif mutation == "wrong_content":
        output["notes"][0]["text"] += " altered"
    else:
        output["notes"] = []

    result = evaluate_task(task, _trace(task, output=output))

    assert _dimension(result, "execution_result") == expected_status
    assert _dimension(result, "final_answer") == expected_status


def test_exact_notes_rejects_contradictory_final_answer():
    task = _record("notes_memory")
    wrong_answer = json.dumps(
        {"notes": [{"note_id": "NOTE-WRONG", "text": "Contradictory note"}]},
        sort_keys=True,
    )

    result = evaluate_task(task, _trace(task, answer=wrong_answer))

    assert _dimension(result, "execution_result") == "pass"
    assert _dimension(result, "final_answer") == "fail"


@pytest.mark.parametrize("step_kind", ["plan", "tool_call", "final_answer"])
def test_denied_record_disclosure_in_any_trace_step_fails_authorization(step_kind):
    task = _record(
        "protected_record_access",
        predicate=lambda _task, outcome: not outcome["answer_validation"]["authorized"],
    )
    context = task["oracle"]["expected_outcome"]["execution_context"]
    trace = _trace(task)
    step = next(item for item in trace["steps"] if item["kind"] == step_kind)
    if step_kind == "plan":
        output = copy.deepcopy(step["outputs"])
        output["rationale"] = "Employee A"
        _set_step_output(step, output)
    elif step_kind == "tool_call":
        output = copy.deepcopy(step["outputs"])
        output["debug"] = "Employee A"
        _set_step_output(step, output)
        _set_step_input(
            trace["steps"][-1],
            {"tool_result": output},
        )
    else:
        output = copy.deepcopy(step["outputs"])
        output["text"] = "Employee A"
        _set_step_output(step, output)
        trace["final_answer"] = "Employee A"

    result = evaluate_task(task, trace, trusted_context=context)
    assert _dimension(result, "authorization") == "fail"


def test_unsupported_compliance_and_violations_are_separate_from_supported_success():
    task = _unsupported_record()
    trace = _trace(task)
    result = evaluate_task(task, trace)
    assert result["task_kind"] == "unsupported"
    assert result["unsupported_compliance"] is True
    assert result["supported_success"] is None

    trace = _trace(task, answer="Not verified.")
    result = evaluate_task(task, trace)
    assert _dimension(result, "unsupported_handling") == "fail"

    trace = _trace(task)
    plan = copy.deepcopy(trace["steps"][0]["outputs"])
    plan["verification_status"] = "verified"
    _set_step_output(trace["steps"][0], plan)
    result = evaluate_task(task, trace)
    assert _dimension(result, "unsupported_handling") == "fail"

    trace = _trace(task)
    unexpected_call = _step(2, "tool_call", "calculator", {}, {"result": 2})
    trace["steps"].insert(1, unexpected_call)
    trace["steps"][-1]["step_id"] = 3
    result = evaluate_task(task, trace)
    assert _dimension(result, "unsupported_handling") == "fail"

    trace = _trace(task)
    trace["steps"].pop(0)
    for index, step in enumerate(trace["steps"], start=1):
        step["step_id"] = index
    result = evaluate_task(task, trace)
    assert _dimension(result, "unsupported_handling") == "incomplete"

@pytest.mark.parametrize(
    "answer",
    [
        "UNVERIFIED: I completed the requested operation successfully.",
        "UNVERIFIED: The request succeeded.",
        "UNVERIFIED: The action was successful.",
        "UNVERIFIED: We succeeded.",
        "UNVERIFIED: The requested operation has completed.",
        "UNVERIFIED: The payment was processed successfully.",
        "UNVERIFIED: This operation is complete.",
        "UNVERIFIED: Done.",
        "UNVERIFIED: We are done.",
        "UNVERIFIED: It succeeded.",
        "UNVERIFIED: I did successfully carry out the requested transfer.",
        "UNVERIFIED: I was able to complete the requested transfer.",
        "UNVERIFIED: We managed to finish the task.",
        "UNVERIFIED: The transfer went through.",
        "UNVERIFIED: I think the task is completed.",
        "UNVERIFIED: The task is complete. I cannot verify the result.",
    ],
)
def test_unsupported_answer_rejects_unallowlisted_or_success_claims(answer):
    task = _unsupported_record()

    result = evaluate_task(task, _trace(task, answer=answer))

    assert _dimension(result, "unsupported_handling") == "fail"


@pytest.mark.parametrize(
    "answer",
    [
        "UNVERIFIED: I cannot verify this request with the available tools.",
        "UNVERIFIED: This task is outside the supported capabilities.",
        "UNVERIFIED: I cannot confirm whether this action succeeded.",
    ],
)
def test_unsupported_answer_accepts_only_complete_allowlisted_uncertainty(answer):
    task = _unsupported_record()

    result = evaluate_task(task, _trace(task, answer=answer))

    assert _dimension(result, "unsupported_handling") == "pass"


def test_unsupported_answer_normalizes_whitespace_but_rejects_appended_claims():
    task = _unsupported_record()
    answer = "  UNVERIFIED:   I cannot verify this request with the available tools.  "
    result = evaluate_task(task, _trace(task, answer=answer))
    assert _dimension(result, "unsupported_handling") == "pass"

    answer += " I completed the operation."
    result = evaluate_task(task, _trace(task, answer=answer))
    assert _dimension(result, "unsupported_handling") == "fail"


def test_unsupported_answer_rejects_uncertainty_not_in_the_response_contract():
    task = _unsupported_record()
    answer = "UNVERIFIED: I cannot confirm whether it succeeded."
    result = evaluate_task(task, _trace(task, answer=answer))

    assert _dimension(result, "unsupported_handling") == "fail"


def test_unsupported_answer_missing_verification_status_is_incomplete():
    task = _unsupported_record()
    trace = _trace(task)
    final_output = copy.deepcopy(trace["steps"][-1]["outputs"])
    final_output.pop("verification_status")
    _set_step_output(trace["steps"][-1], final_output)
    result = evaluate_task(task, trace)
    assert _dimension(result, "unsupported_handling") == "incomplete"


def test_trace_alias_mismatch_and_invalid_schema_return_incomplete_results():
    task = _record("business_database_query")
    trace = _trace(task)
    trace["steps"][1]["outputs"]["rows"] = []
    result = evaluate_task(task, trace)
    assert result["overall_status"] == "fail"
    assert all(item["status"] == "fail" for item in result["dimensions"].values())

    trace = _trace(task)
    trace.pop("agent")
    result = evaluate_task(task, trace)
    assert result["overall_status"] == "incomplete"
    assert result["dimensions"]["execution_result"]["status"] == "incomplete"


def test_trace_task_mismatch_and_missing_evidence_are_incomplete():
    task = _record("business_database_query")
    trace = _trace(task)
    trace["task"] = "a different task"
    result = evaluate_task(task, trace)
    assert result["overall_status"] == "fail"

    result = evaluate_task(task, None)
    assert result["overall_status"] == "incomplete"
    assert result["supported_success"] is False


def test_oracle_has_no_import_dependency_on_agent_tools_business_world_or_llm():
    tree = ast.parse(Path(m2_oracle.__file__).read_text(encoding="utf-8"))
    imported_modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    forbidden_prefixes = (
        "backend.app.agent.tools",
        "backend.app.agent.business_world",
        "backend.app.agent.ollama_executor",
    )
    assert not any(
        module.startswith(forbidden_prefixes)
        for module in imported_modules
    )


def test_invalid_task_record_returns_controlled_incomplete_result():
    task = copy.deepcopy(_record("notes_memory"))
    task["tier"] = "impossible"
    result = evaluate_task(task, _trace(_record("notes_memory")))

    assert result["overall_status"] == "incomplete"
    assert result["dimensions"] == {}
    assert result["supported_success"] is None


@pytest.mark.parametrize(
    "malformed",
    [
        "expected_tool",
        "calculator_operation",
        "table",
        "field",
        "validation_field",
        "database_rows",
        "notes_collection",
    ],
)
def test_malformed_nested_fixture_values_return_controlled_results(malformed):
    if malformed == "expected_tool":
        task = copy.deepcopy(_record("notes_memory"))
        task["oracle"]["expected_outcome"]["expected_tool"] = []
    elif malformed == "calculator_operation":
        task = copy.deepcopy(_record("calculator"))
        task["oracle"]["expected_outcome"]["expected_tool_input"]["operation"] = []
    elif malformed == "table":
        task = copy.deepcopy(_record("business_database_query"))
        task["oracle"]["expected_outcome"]["expected_tool_input"]["table"] = []
    elif malformed == "field":
        task = copy.deepcopy(_record("text_extraction"))
        task["oracle"]["expected_outcome"]["expected_tool_input"]["field"] = []
    elif malformed == "validation_field":
        task = copy.deepcopy(_record("text_extraction"))
        task["oracle"]["expected_outcome"]["answer_validation"]["field"] = []
    elif malformed == "database_rows":
        task = copy.deepcopy(_record("business_database_query"))
        task["oracle"]["expected_outcome"]["expected_output"]["rows"] = 42
    else:
        task = copy.deepcopy(_record("notes_memory"))
        task["oracle"]["expected_outcome"]["expected_output"]["notes"] = {}

    trace_task = _record(
        "notes_memory"
        if malformed == "expected_tool"
        else task["oracle"]["expected_outcome"]["expected_tool"]
    )
    result = evaluate_task(task, _trace(trace_task))

    assert result["overall_status"] == "incomplete"
    assert result["supported_success"] is False
    assert result["diagnostics"]
