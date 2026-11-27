"""Contract-only tests for the versioned M0-A JSON schemas."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


SCHEMA_DIR = Path(__file__).resolve().parents[1] / "shared" / "schemas"
SCHEMA_NAMES = (
    "execution_trace_v1",
    "evidence_summary_v1",
    "failure_categories",
    "agent_config",
    "task",
    "reviewer_finding",
    "reviewer_result_v1",
    "canary",
    "patch_contract",
    "version",
    "reviewer_trust_profile",
)


def load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / f"{name}.json").read_text(encoding="utf-8"))


def local_registry() -> Registry:
    registry = Registry()
    for name in SCHEMA_NAMES:
        schema = load_schema(name)
        registry = registry.with_resource(
            schema["$id"],
            Resource.from_contents(schema),
        )
    return registry


def test_all_m0a_schemas_are_valid_json_schema():
    for name in SCHEMA_NAMES:
        Draft202012Validator.check_schema(load_schema(name))


def test_failure_categories_and_mapping_statuses_are_explicit():
    schema = load_schema("failure_categories")
    example = schema["examples"][0]
    categories = {entry["category"] for entry in example["categories"]}
    assert categories == {
        "wrong_tool",
        "wrong_calculation",
        "skipped_step",
        "invented_fact",
        "safety",
    }

    mappings = {
        entry["mutation_type"]: entry
        for entry in example["mutation_mapping"]
    }
    assert mappings["wrong_arguments"]["mapping_status"] == "provisional"
    assert mappings["wrong_arguments"]["canonical_category"] == "wrong_calculation"
    assert mappings["inconsistent_answer"]["mapping_status"] == "provisional"
    assert "oracle validation is required in M2" in (
        mappings["inconsistent_answer"]["rationale"]
    )
    assert mappings["incomplete_answer"]["mapping_status"] == "unresolved"
    assert mappings["incomplete_answer"]["canonical_category"] is None


def test_clean_canary_contract_allows_no_failure_category():
    validator = Draft202012Validator(load_schema("canary"))
    clean_control = {
        "schema_version": "1.0",
        "canary_id": "canary-control-1",
        "source_kind": "clean_control",
        "source_trace_ref": {
            "execution_id": "exec-source-1",
            "trace_hash": "sha256:" + "a" * 64,
        },
        "copied_trace_ref": {
            "copy_id": "copy-control-1",
            "storage_scope": "reviewer_canaries",
        },
        "mutation_type": None,
        "failure_category": None,
        "mapping_status": "not_applicable",
        "isolation": {
            "live_execution_record_created": False,
            "reviewer_input_contains_canary_metadata": False,
        },
    }
    assert list(validator.iter_errors(clean_control)) == []


def test_canary_contract_represents_injected_and_replayed_sources():
    validator = Draft202012Validator(load_schema("canary"))
    common = {
        "schema_version": "1.0",
        "canary_id": "canary-1",
        "source_trace_ref": {
            "execution_id": "exec-source-1",
            "trace_hash": "sha256:" + "b" * 64,
        },
        "copied_trace_ref": {
            "copy_id": "copy-1",
            "storage_scope": "reviewer_canaries",
        },
        "isolation": {
            "live_execution_record_created": False,
            "reviewer_input_contains_canary_metadata": False,
        },
    }
    injected = {
        **common,
        "source_kind": "injected_fault",
        "mutation_type": "wrong_arguments",
        "failure_category": "wrong_calculation",
        "mapping_status": "provisional",
    }
    replayed = {
        **common,
        "source_kind": "replayed_real_failure",
        "mutation_type": None,
        "failure_category": "wrong_calculation",
        "mapping_status": "confirmed",
    }
    assert list(validator.iter_errors(injected)) == []
    assert list(validator.iter_errors(replayed)) == []


def test_patch_contract_restricts_sections_and_prohibits_code():
    schema = load_schema("patch_contract")
    validator = Draft202012Validator(schema)
    patch = {
        "schema_version": "1.0",
        "patch_id": "patch-1",
        "target_config_version": "cfg-1",
        "target_config_hash": "sha256:" + "c" * 64,
        "source_finding_ids": ["finding-1"],
        "objective": {
            "metric": "targeted_task_success",
            "comparison": "at_least",
            "target": 0.9,
            "unit": "fraction",
        },
        "resource_limits": {
            "latency_ms_cap": 5000,
            "cost_usd_cap": 1,
        },
        "rollback_condition": {
            "metric": "safety_failures",
            "comparison": "greater_than",
            "threshold": 0,
        },
        "affected_task_tags": ["apple-routing"],
        "edit_operations": [
            {
                "operation": "replace",
                "section": "tool_routing_rules",
                "path": "/apple_color/tool_name",
                "value": "unsupported",
            }
        ],
        "generated_code": False,
    }
    assert list(validator.iter_errors(patch)) == []

    disallowed_section = json.loads(json.dumps(patch))
    disallowed_section["edit_operations"][0]["section"] = "python_source"
    assert list(validator.iter_errors(disallowed_section))

    generated_code = json.loads(json.dumps(patch))
    generated_code["generated_code"] = True
    assert list(validator.iter_errors(generated_code))


def test_reviewer_result_separates_findings_from_verifier_output():
    schema = load_schema("reviewer_result_v1")
    validator = Draft202012Validator(schema, registry=local_registry())
    result = {
        "schema_version": "1.0",
        "execution_id": "exec-1",
        "findings": [
            {
                "schema_version": "1.0",
                "reviewer_id": "task-completion-reviewer",
                "role": "task_completion",
                "model_name": "local-model",
                "prompt_version": "p1",
                "verdict": "pass",
                "cited_step_id": 3,
                "evidence_quote": "The result is 42.",
                "confidence": 0.8,
            }
        ],
        "deterministic_verifier": {
            "verdict": "pass",
            "checks": [
                {
                    "check_id": "tool_result_verified",
                    "status": "pass",
                    "evidence_step_ids": [2],
                    "detail": "Oracle result matched.",
                }
            ],
        },
        "verdict": "pass",
        "execution_score": 1.0,
        "disagreement": False,
        "escalation": "none",
    }
    assert list(validator.iter_errors(result)) == []


def test_task_and_trust_profile_are_distinct_versioned_records():
    task_schema = load_schema("task")
    trust_schema = load_schema("reviewer_trust_profile")
    assert task_schema["properties"]["schema_version"] == {"const": "1.0"}
    assert trust_schema["properties"]["schema_version"] == {"const": "1.0"}
    assert "execution_score" not in trust_schema["properties"]
