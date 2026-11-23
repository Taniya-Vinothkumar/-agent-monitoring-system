"""Module coordination (Person 1). STATUS: REAL.

The only place that knows the whole pipeline:

    TaskRequest -> agent -> trace -> evidence -> reviewer -> database

Person 1's modules talk in Pydantic models; the reviewer (Person 2) talks in
plain dicts that follow shared/schemas. The conversion happens here, and the
reviewer's output is re-validated with Pydantic before it is stored.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.agent.executor import MockAgentExecutor
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


def _as_utc(value: datetime) -> datetime:
    """SQLite drops tzinfo; every timestamp we store is UTC, so restore it."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _write_json(directory: Path, name: str, payload: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def process_task(
    request: TaskRequest, session: Session, settings: Settings
) -> tuple[ExecutionTrace, EvidenceSummary, ReviewerResult]:
    trace = MockAgentExecutor().run(request)
    evidence = aggregate_evidence(trace)

    trace_dict = trace.model_dump(mode="json")
    evidence_dict = evidence.model_dump(mode="json")
    review_dict = review_execution(trace_dict, evidence_dict, latency_budget_ms=settings.latency_budget_ms)
    review = ReviewerResult.model_validate(review_dict)
    review_dict = review.model_dump(mode="json")

    session.add(ExecutionRecord(
        execution_id=trace.execution_id, task=trace.task, status=trace.status,
        created_at=trace.started_at, total_duration_ms=trace.total_duration_ms,
        trace=trace_dict, evidence=evidence_dict,
    ))
    session.add(ReviewRecord(
        review_id=review.review_id, execution_id=trace.execution_id, created_at=review.created_at,
        verdict=review.verdict, trust_score=review.trust.score, review=review_dict,
    ))
    session.commit()

    if settings.persist_json_files:
        _write_json(settings.data_dir / "executions", trace.execution_id, trace_dict)
        _write_json(settings.data_dir / "evaluation", trace.execution_id, review_dict)
    return trace, evidence, review


def get_trace(session: Session, execution_id: str) -> ExecutionTrace | None:
    record = session.get(ExecutionRecord, execution_id)
    return ExecutionTrace.model_validate(record.trace) if record else None


def get_evidence(session: Session, execution_id: str) -> EvidenceSummary | None:
    record = session.get(ExecutionRecord, execution_id)
    return EvidenceSummary.model_validate(record.evidence) if record else None


def get_review(session: Session, execution_id: str) -> ReviewerResult | None:
    record = session.scalars(
        select(ReviewRecord).where(ReviewRecord.execution_id == execution_id)
        .order_by(ReviewRecord.created_at.desc())
    ).first()
    return ReviewerResult.model_validate(record.review) if record else None


def list_executions(session: Session) -> list[ExecutionListItem]:
    rows = session.execute(
        select(ExecutionRecord, ReviewRecord)
        .outerjoin(ReviewRecord, ReviewRecord.execution_id == ExecutionRecord.execution_id)
        .order_by(ExecutionRecord.created_at.desc())
    ).all()
    return [
        ExecutionListItem(
            execution_id=e.execution_id, task=e.task, status=e.status, created_at=_as_utc(e.created_at),
            total_duration_ms=e.total_duration_ms, fault_injection=e.trace.get("fault_injection"),
            verdict=r.verdict if r else None, trust_score=r.trust_score if r else None,
        )
        for e, r in rows
    ]
