
"""Module coordination.

TaskRequest -> agent -> trace -> evidence -> reviewers -> database

The deterministic reviewer remains authoritative.
AI specialist reviews are advisory.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.agent.guardian_adapter import GuardianAgentAdapter
from backend.app.agent.trace_compat import v1_trace_to_legacy
from backend.app.api.schemas import (
    EvidenceSummary,
    ExecutionListItem,
    ExecutionTrace,
    ReviewerResult,
    TaskRequest,
)
from backend.app.config import Settings
from backend.app.database.models import ExecutionRecord, ReviewRecord
from backend.app.monitoring.evidence import aggregate_evidence
from reviewer import review_execution
from reviewer.specialists import run_specialist_reviewers


def _as_utc(value: datetime) -> datetime:
    """Restore UTC timezone after SQLite removes timezone information."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _write_json(directory: Path, name: str, payload: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def process_task(
    request: TaskRequest,
    session: Session,
    settings: Settings,
) -> tuple[ExecutionTrace, EvidenceSummary, ReviewerResult]:
    """Execute a task using the configured agent and review its output."""

    # Step 1: Run the configured agent through the frozen adapter.
    adapter = GuardianAgentAdapter(settings)
    versioned_trace = adapter.run_task(
        {
            "text": request.task,
            "fault_injection": request.fault_injection,
        }
    )
    trace = ExecutionTrace.model_validate(v1_trace_to_legacy(versioned_trace))

    # Step 2: Aggregate evidence.
    evidence = aggregate_evidence(trace)

    # Step 3: Convert models into dictionaries.
    trace_dict = trace.model_dump(mode="json")
    evidence_dict = evidence.model_dump(mode="json")

    # Step 4: Run authoritative deterministic reviewer.
    review_dict = review_execution(
        trace_dict,
        evidence_dict,
        latency_budget_ms=settings.latency_budget_ms,
    )

    # Step 5: Run optional AI specialist reviewers.
    if settings.specialist_reviews_enabled:
        specialist_reviews = run_specialist_reviewers(
            trace_dict,
            evidence_dict,
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout_seconds=settings.ollama_specialist_timeout_seconds,
        )
    else:
        specialist_reviews = []

    # Specialist results are advisory.
    # They cannot modify the deterministic verdict or trust score.
    review_dict["specialist_reviews"] = specialist_reviews

    # Step 6: Validate complete reviewer output.
    review = ReviewerResult.model_validate(review_dict)
    review_dict = review.model_dump(mode="json")

    # Step 7: Persist execution.
    session.add(
        ExecutionRecord(
            execution_id=trace.execution_id,
            task=trace.task,
            status=trace.status,
            created_at=trace.started_at,
            total_duration_ms=trace.total_duration_ms,
            trace=trace_dict,
            evidence=evidence_dict,
        )
    )

    # Step 8: Persist complete reviewer result.
    session.add(
        ReviewRecord(
            review_id=review.review_id,
            execution_id=trace.execution_id,
            created_at=review.created_at,
            verdict=review.verdict,
            trust_score=review.trust.score,
            review=review_dict,
        )
    )

    session.commit()

    # Step 9: Optionally save JSON artifacts.
    if settings.persist_json_files:
        _write_json(
            settings.data_dir / "executions",
            trace.execution_id,
            trace_dict,
        )
        _write_json(
            settings.data_dir / "executions_v1",
            trace.execution_id,
            dict(versioned_trace),
        )
        _write_json(
            settings.data_dir / "evaluation",
            trace.execution_id,
            review_dict,
        )

    return trace, evidence, review


def get_trace(
    session: Session,
    execution_id: str,
) -> ExecutionTrace | None:
    record = session.get(ExecutionRecord, execution_id)
    return ExecutionTrace.model_validate(record.trace) if record else None


def get_evidence(
    session: Session,
    execution_id: str,
) -> EvidenceSummary | None:
    record = session.get(ExecutionRecord, execution_id)
    return EvidenceSummary.model_validate(record.evidence) if record else None


def get_review(
    session: Session,
    execution_id: str,
) -> ReviewerResult | None:
    record = session.scalars(
        select(ReviewRecord)
        .where(ReviewRecord.execution_id == execution_id)
        .order_by(ReviewRecord.created_at.desc())
    ).first()

    return ReviewerResult.model_validate(record.review) if record else None


def list_executions(
    session: Session,
) -> list[ExecutionListItem]:
    rows = session.execute(
        select(ExecutionRecord, ReviewRecord)
        .outerjoin(
            ReviewRecord,
            ReviewRecord.execution_id == ExecutionRecord.execution_id,
        )
        .order_by(ExecutionRecord.created_at.desc())
    ).all()

    return [
        ExecutionListItem(
            execution_id=e.execution_id,
            task=e.task,
            status=e.status,
            created_at=_as_utc(e.created_at),
            total_duration_ms=e.total_duration_ms,
            fault_injection=e.trace.get("fault_injection"),
            verdict=r.verdict if r else None,
            trust_score=r.trust_score if r else None,
        )
        for e, r in rows
    ]
