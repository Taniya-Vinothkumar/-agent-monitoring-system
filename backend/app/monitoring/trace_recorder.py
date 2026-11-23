"""Execution trace collection (Person 1). STATUS: REAL.

Usage:
    recorder = TraceRecorder(task, agent_info)
    with recorder.step("tool_call", "calculator", {"expression": "1+1"}) as s:
        s.output = {"result": 2}
    trace = recorder.finalize(final_answer="...")

If the `with` body raises, the step is recorded with status "error" and the
exception is re-raised, so the caller decides how to continue.
"""
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from backend.app.api.schemas import AgentInfo, ExecutionTrace, TraceStep


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StepHandle:
    """Set `.output` inside the `with` block."""

    def __init__(self) -> None:
        self.output: dict[str, Any] | None = None


class TraceRecorder:
    def __init__(self, task: str, agent: AgentInfo, fault_injection: str | None = None) -> None:
        self.execution_id = f"exec_{uuid.uuid4().hex[:12]}"
        self.task = task
        self.agent = agent
        self.fault_injection = fault_injection
        self._started_at = _utcnow()
        self._t0 = time.perf_counter()
        self._steps: list[TraceStep] = []

    @property
    def steps(self) -> list[TraceStep]:
        return list(self._steps)

    def _append(self, type_: str, name: str, input_: dict, handle: StepHandle,
                error: str | None, timestamp: datetime, t0: float) -> None:
        self._steps.append(
            TraceStep(
                step_id=len(self._steps) + 1,
                type=type_,
                name=name,
                status="error" if error else "ok",
                input=input_,
                output=None if error else handle.output,
                error=error,
                timestamp=timestamp,
                duration_ms=round((time.perf_counter() - t0) * 1000, 3),
            )
        )

    @contextmanager
    def step(self, type_: str, name: str, input_: dict[str, Any]) -> Iterator[StepHandle]:
        handle = StepHandle()
        timestamp, t0 = _utcnow(), time.perf_counter()
        try:
            yield handle
        except Exception as exc:
            self._append(type_, name, input_, handle, str(exc) or exc.__class__.__name__, timestamp, t0)
            raise
        self._append(type_, name, input_, handle, None, timestamp, t0)

    def finalize(self, final_answer: str | None) -> ExecutionTrace:
        failed = final_answer is None or any(s.status == "error" for s in self._steps)
        return ExecutionTrace(
            execution_id=self.execution_id,
            task=self.task,
            status="failed" if failed else "completed",
            agent=self.agent,
            fault_injection=self.fault_injection,
            started_at=self._started_at,
            finished_at=_utcnow(),
            total_duration_ms=round((time.perf_counter() - self._t0) * 1000, 3),
            steps=self._steps,
            final_answer=final_answer,
        )
