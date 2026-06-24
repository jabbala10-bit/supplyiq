"""Network optimization routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from src.api.dependencies import get_network_solver, get_storage_service, require_api_token
from src.domain.exceptions import InfeasibleProblemError, NetworkOptimizationError
from src.domain.network_schemas import NetworkOptimizationRequest, NetworkOptimizationResult
from src.services.network.network_solver import NetworkOptimizationSolver
from src.services.storage.sqlite_service import SQLiteStorageService

router = APIRouter(prefix="/network", tags=["network"], dependencies=[Depends(require_api_token)])


@router.post("/solve", response_model=NetworkOptimizationResult, status_code=201)
def solve_network(
    request: NetworkOptimizationRequest,
    solver: NetworkOptimizationSolver = Depends(get_network_solver),
    storage: SQLiteStorageService = Depends(get_storage_service),
) -> NetworkOptimizationResult:
    try:
        result = solver.solve(request)
    except InfeasibleProblemError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NetworkOptimizationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    storage.save_network_plan(request, result)
    return result


@router.get("/plans/{plan_id}", response_model=NetworkOptimizationResult)
def get_plan(plan_id: str, storage: SQLiteStorageService = Depends(get_storage_service)) -> NetworkOptimizationResult:
    pair = storage.get_network_plan(plan_id)
    if pair is None:
        raise HTTPException(status_code=404, detail=f"Network plan {plan_id} not found")
    return pair[1]
