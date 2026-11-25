
"""API request/response models (Person 1). STATUS: REAL.

These Pydantic models mirror shared/schemas/*.json. If you change one, change
the other in the same pull request; tests/test_integration.py fails when
the sample data stops validating against both.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


FaultInjection = Literal["wrong_tool_result", "inconsistent_answer"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- Requests ------------------------------------------------------------
class TaskRequest(_Strict):
    task: str = Field(min_length=1, max_length=500)
    fault_injection: FaultInjection | None = Field(
        default=None,
        description=(
            "TEST-ONLY: deliberately corrupt the run so the reviewer "
            "has something to catch."
        ),
    )


# ---- Execution trace (shared/schemas/execution.json) ---------------------
class AgentInfo(_Strict):
    name: str
    version: str
    mode: Literal["mock_rule_based", "ollama"]


class TraceStep(_Strict):
    step_id: int = Field(ge=1)
    type: Literal["plan", "tool_call", "final_answer"]
    name: str
    status: Literal["ok", "error"]
    input: dict[str, Any]
    output: dict[str, Any] | None
    error: str | None
    timestamp: datetime
    duration_ms: float = Field(ge=0)


class ExecutionTrace(_Strict):
    execution_id: str
    task: str = Field(min_length=1, max_length=500)
    status: Literal["completed", "failed"]
    agent: AgentInfo
    fault_injection: FaultInjection | None = None
    started_at: datetime
    finished_at: datetime
    total_duration_ms: float = Field(ge=0)
    steps: list[TraceStep]
    final_answer: str | None


# ---- Evidence (shared/schemas/evidence.json) -----------------------------
class EvidenceError(_Strict):
    step_id: int = Field(ge=1)
    message: str


class VerifiableClaim(_Strict):
    step_id: int = Field(ge=1)
    kind: Literal["arithmetic", "word_count"]
    input: str
    claimed_result: float


class EvidenceSummary(_Strict):
    execution_id: str
    total_steps: int = Field(ge=0)
    step_type_counts: dict[str, int]
    tool_call_count: int = Field(ge=0)
    tools_used: list[str]
    error_count: int = Field(ge=0)
    errors: list[EvidenceError]
    total_duration_ms: float = Field(ge=0)
    has_final_answer: bool
    final_answer: str | None
    verifiable_claims: list[VerifiableClaim]


# ---- Reviewer result (shared/schemas/reviewer.json) ----------------------
class ReviewerInfo(_Strict):
    name: str
    version: str
    mode: Literal["rule_based"]


class ReviewCheck(_Strict):
    check_id: str
    description: str
    severity: Literal["info", "warning", "critical"]
    status: Literal["pass", "fail", "skipped"]
    evidence_step_ids: list[int]
    detail: str


class AuditFinding(_Strict):
    audit_id: str
    status: Literal["pass", "fail"]
    description: str
    detail: str


class AuditResult(_Strict):
    passed: bool
    findings: list[AuditFinding]


class TrustScore(_Strict):
    score: float = Field(ge=0, le=1)
    lower: float = Field(ge=0, le=1)
    upper: float = Field(ge=0, le=1)
    method: Literal["beta_prior_uncalibrated"]
    n_checks: int = Field(ge=0)
    audit_penalty_applied: bool
    critical_failure_cap_applied: bool


class Improvement(_Strict):
    improvement_id: str
    target_check: str
    suggestion: str
    requires_human_approval: Literal[True]
    status: Literal["proposed"]


# ---- Independent AI specialist reviewers -------------------------------
class SpecialistCheck(_Strict):
    check_id: str
    status: Literal["pass", "fail", "skipped"]
    detail: str


class SpecialistReview(_Strict):
    reviewer: str
    role: Literal["tool_use", "task_completion"]
    version: str
    mode: Literal["ollama"]
    model: str
    status: Literal[
        "completed",
        "timeout",
        "unavailable",
        "invalid_response",
    ]
    verdict: Literal["pass", "needs_attention", "fail"]
    checks: list[SpecialistCheck]
    summary: str
    latency_ms: float = Field(ge=0)


class ReviewerResult(_Strict):
    review_id: str
    execution_id: str
    reviewer: ReviewerInfo
    created_at: datetime
    checks: list[ReviewCheck]
    score: float = Field(ge=0, le=1)
    verdict: Literal["pass", "needs_attention", "fail"]
    audit: AuditResult
    trust: TrustScore
    improvements: list[Improvement]

    # Advisory AI reviews. They do not override the deterministic reviewer.
    # Default preserves compatibility with previously stored review records.
    specialist_reviews: list[SpecialistReview] = Field(
        default_factory=list
    )


# ---- API-only responses --------------------------------------------------
class TaskSubmitResponse(_Strict):
    execution_id: str
    review_id: str
    status: Literal["completed", "failed"]
    verdict: Literal["pass", "needs_attention", "fail"]
    trust_score: float


class ExecutionListItem(_Strict):
    execution_id: str
    task: str
    status: Literal["completed", "failed"]
    created_at: datetime
    total_duration_ms: float
    fault_injection: FaultInjection | None = None
    verdict: Literal["pass", "needs_attention", "fail"] | None
    trust_score: float | None


class HealthResponse(_Strict):
    status: Literal["ok"]
    app: str
