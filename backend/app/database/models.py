"""Database models (Person 1). STATUS: REAL.

Traces, evidence and reviews are stored as JSON documents that follow the
schemas in shared/schemas. Only the fields needed for listing/filtering are
real columns.
"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database.connection import Base


class ExecutionRecord(Base):
    __tablename__ = "executions"

    execution_id: Mapped[str] = mapped_column(String, primary_key=True)
    task: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    total_duration_ms: Mapped[float] = mapped_column(Float)
    trace: Mapped[dict] = mapped_column(JSON)       # ExecutionTrace
    evidence: Mapped[dict] = mapped_column(JSON)    # EvidenceSummary


class ReviewRecord(Base):
    __tablename__ = "reviews"

    review_id: Mapped[str] = mapped_column(String, primary_key=True)
    execution_id: Mapped[str] = mapped_column(ForeignKey("executions.execution_id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verdict: Mapped[str] = mapped_column(String)
    trust_score: Mapped[float] = mapped_column(Float)
    review: Mapped[dict] = mapped_column(JSON)      # ReviewerResult
