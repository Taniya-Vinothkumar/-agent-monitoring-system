"""API endpoints (Person 1). STATUS: REAL. Contract: docs/api_contract.md."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.api.schemas import (
    AuthorizationRequest,
    AuthorizationResponse,
    EvidenceSummary,
    ExecutionListItem,
    ExecutionTrace,
    HealthResponse,
    ReviewerResult,
    TaskRequest,
    TaskSubmitResponse,
)
from backend.app.services.authorization import (
    AuthorizationError,
    authorize_reviewers,
)
from backend.app.config import Settings, get_settings
from backend.app.database.connection import get_session
from backend.app.services import integration

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(settings: Settings = Depends(get_settings)):
    return HealthResponse(status="ok", app=settings.app_name)


@router.post("/tasks", response_model=TaskSubmitResponse, status_code=status.HTTP_201_CREATED)
def submit_task(
    request: TaskRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    """Run the agent, record the trace, aggregate evidence, review it. Synchronous."""
    trace, _, review = integration.process_task(request, session, settings)
    return TaskSubmitResponse(
        execution_id=trace.execution_id, review_id=review.review_id, status=trace.status,
        verdict=review.verdict, trust_score=review.trust.score,
    )


@router.get("/executions", response_model=list[ExecutionListItem])
def list_executions(session: Session = Depends(get_session)):
    return integration.list_executions(session)


def _or_404(value, what: str, execution_id: str):
    if value is None:
        raise HTTPException(status_code=404, detail=f"{what} not found for '{execution_id}'")
    return value


@router.get("/executions/{execution_id}", response_model=ExecutionTrace)
def get_execution(execution_id: str, session: Session = Depends(get_session)):
    return _or_404(integration.get_trace(session, execution_id), "Execution", execution_id)


@router.get("/executions/{execution_id}/evidence", response_model=EvidenceSummary)
def get_evidence(execution_id: str, session: Session = Depends(get_session)):
    return _or_404(integration.get_evidence(session, execution_id), "Evidence", execution_id)


@router.get("/executions/{execution_id}/review", response_model=ReviewerResult)
def get_review(execution_id: str, session: Session = Depends(get_session)):
    return _or_404(integration.get_review(session, execution_id), "Review", execution_id)


@router.post(
    "/reviewer/authorize",
    response_model=AuthorizationResponse,
    status_code=status.HTTP_200_OK,
)
def authorize_reviewer_endpoint(
    request: AuthorizationRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    """Measure reviewer reliability using stored execution evidence."""

    try:
        result = authorize_reviewers(
            session=session,
            execution_ids=request.execution_ids,
            settings=settings,
            include_specialists=request.include_specialists,
        )
        return AuthorizationResponse(**result)

    except AuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Authorization could not be completed: {exc}",
        ) from exc
