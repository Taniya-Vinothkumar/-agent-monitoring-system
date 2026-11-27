"""Conversion between the frozen M0-A trace and the existing API trace."""

import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

V1_TRACE_SCHEMA = (
    Path(__file__).resolve().parents[3]
    / "shared"
    / "schemas"
    / "execution_trace_v1.json"
)


def _validate_v1(trace: Mapping[str, Any]) -> None:
    schema = json.loads(V1_TRACE_SCHEMA.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(dict(trace)),
        key=lambda error: list(map(str, error.path)),
    )
    if errors:
        detail = "; ".join(
            f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
            for error in errors
        )
        raise ValueError(f"ExecutionTraceV1 failed validation: {detail}")


def legacy_trace_to_v1(
    legacy_trace: Mapping[str, Any], config_version: str
) -> dict[str, Any]:
    """Add M0-A version and normalized aliases without changing legacy fields."""
    data = dict(legacy_trace)
    steps = []
    for legacy_step in data["steps"]:
        step = dict(legacy_step)
        kind = step["type"]
        steps.append(
            {
                **step,
                "kind": kind,
                "tool_name": step["name"] if kind == "tool_call" else None,
                "inputs": step["input"],
                "outputs": step["output"],
            }
        )
    versioned = {
        "schema_version": "1.0",
        "execution_id": data["execution_id"],
        "task": data["task"],
        "status": data["status"],
        "agent": data["agent"],
        "config_version": config_version,
        "fault_injection": data.get("fault_injection"),
        "started_at": data["started_at"],
        "finished_at": data["finished_at"],
        "total_duration_ms": data["total_duration_ms"],
        "steps": steps,
        "final_answer": data["final_answer"],
    }
    _validate_v1(versioned)
    return versioned


def v1_trace_to_legacy(versioned_trace: Mapping[str, Any]) -> dict[str, Any]:
    """Validate alias consistency and return the established API trace shape."""
    _validate_v1(versioned_trace)
    steps = []
    for step in versioned_trace["steps"]:
        if step["kind"] != step["type"]:
            raise ValueError("Trace kind/type aliases differ.")
        if step["kind"] == "tool_call" and step["tool_name"] != step["name"]:
            raise ValueError("Trace tool_name/name aliases differ.")
        if step["inputs"] != step["input"] or step["outputs"] != step["output"]:
            raise ValueError("Trace normalized/legacy aliases differ.")
        steps.append(
            {
                "step_id": step["step_id"],
                "type": step["type"],
                "name": step["name"],
                "status": step["status"],
                "input": step["input"],
                "output": step["output"],
                "error": step["error"],
                "timestamp": step["timestamp"],
                "duration_ms": step["duration_ms"],
            }
        )
    return {
        "execution_id": versioned_trace["execution_id"],
        "task": versioned_trace["task"],
        "status": versioned_trace["status"],
        "agent": versioned_trace["agent"],
        "fault_injection": versioned_trace.get("fault_injection"),
        "started_at": versioned_trace["started_at"],
        "finished_at": versioned_trace["finished_at"],
        "total_duration_ms": versioned_trace["total_duration_ms"],
        "steps": steps,
        "final_answer": versioned_trace["final_answer"],
    }
