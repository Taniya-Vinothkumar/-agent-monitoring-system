"""M0-A adapter interface; implementations are added in later milestones."""

from typing import Any, Mapping, Protocol


class AgentAdapter(Protocol):
    """Contract for task execution and candidate configuration management."""

    def run_task(
        self,
        task: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        """Run a task and return a value conforming to ExecutionTraceV1."""
        ...

    def get_config(self) -> Mapping[str, Any]:
        """Return the currently active configuration."""
        ...

    def apply_config(self, config_copy: Mapping[str, Any]) -> Mapping[str, Any]:
        """Validate or create a candidate; never activate or change live config."""
        ...
