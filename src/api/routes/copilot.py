"""Copilot natural-language routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from src.api.dependencies import get_copilot_orchestrator, require_api_token
from src.domain.copilot_schemas import CopilotQuery, CopilotResponse
from src.domain.exceptions import CopilotError, PlanNotFoundError
from src.services.copilot.orchestrator import CopilotOrchestrator

router = APIRouter(prefix="/copilot", tags=["copilot"], dependencies=[Depends(require_api_token)])


@router.post("/ask", response_model=CopilotResponse)
def ask_copilot(
    query: CopilotQuery, orchestrator: CopilotOrchestrator = Depends(get_copilot_orchestrator)
) -> CopilotResponse:
    """
    Ask a natural-language question about a previously-solved plan.
    "Why" questions are answered from the existing plan data; "what if"
    questions trigger a real re-solve and return a new_plan_id.
    """
    try:
        return orchestrator.handle_query(query)
    except PlanNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CopilotError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
