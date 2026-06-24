"""Replenishment planning routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from src.api.dependencies import get_replenishment_solver, get_storage_service, require_api_token
from src.domain.exceptions import ReplenishmentError
from src.domain.replenishment_schemas import ReplenishmentPlanRequest, ReplenishmentPlanResult
from src.services.replenishment.replenishment_solver import ReplenishmentSolver
from src.services.storage.sqlite_service import SQLiteStorageService

router = APIRouter(prefix="/replenishment", tags=["replenishment"], dependencies=[Depends(require_api_token)])


@router.post("/solve", response_model=ReplenishmentPlanResult, status_code=201)
def solve_replenishment(
    request: ReplenishmentPlanRequest,
    solver: ReplenishmentSolver = Depends(get_replenishment_solver),
    storage: SQLiteStorageService = Depends(get_storage_service),
) -> ReplenishmentPlanResult:
    try:
        result = solver.solve(request)
    except ReplenishmentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    storage.save_replenishment_plan(request, result)
    return result


@router.get("/plans/{plan_id}", response_model=ReplenishmentPlanResult)
def get_plan(plan_id: str, storage: SQLiteStorageService = Depends(get_storage_service)) -> ReplenishmentPlanResult:
    pair = storage.get_replenishment_plan(plan_id)
    if pair is None:
        raise HTTPException(status_code=404, detail=f"Replenishment plan {plan_id} not found")
    return pair[1]
