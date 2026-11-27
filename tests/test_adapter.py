"""Contract-only tests for the M0-A adapter Protocol."""

import inspect
from typing import Any, Mapping

from backend.app.agent.adapter import AgentAdapter


def test_adapter_exposes_only_the_three_approved_methods():
    assert {"run_task", "get_config", "apply_config"} <= set(
        AgentAdapter.__dict__
    )
    assert "activate" not in AgentAdapter.__dict__
    assert "rollback" not in AgentAdapter.__dict__


def test_run_task_signature_accepts_optional_context():
    signature = inspect.signature(AgentAdapter.run_task)
    assert list(signature.parameters) == ["self", "task", "context"]
    assert signature.parameters["task"].annotation == Mapping[str, Any]
    assert signature.parameters["context"].default is None


def test_apply_config_signature_takes_a_config_copy():
    signature = inspect.signature(AgentAdapter.apply_config)
    assert list(signature.parameters) == ["self", "config_copy"]
    assert "never activate or change live config" in (
        AgentAdapter.apply_config.__doc__ or ""
    )
