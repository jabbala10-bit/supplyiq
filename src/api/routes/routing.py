"""Vehicle routing routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from src.api.dependencies import get_routing_solver, get_storage_service, require_api_token
from src.domain.exceptions import RoutingError
from src.domain.routing_schemas import VehicleRoutingRequest, VehicleRoutingResult
from src.services.routing.vrp_solver import VehicleRoutingSolver
from src.services.storage.sqlite_service import SQLiteStorageService

router = APIRouter(prefix="/routing", tags=["routing"], dependencies=[Depends(require_api_token)])


@router.post("/solve", response_model=VehicleRoutingResult, status_code=201)
def solve_routing(
    request: VehicleRoutingRequest,
    solver: VehicleRoutingSolver = Depends(get_routing_solver),
    storage: SQLiteStorageService = Depends(get_storage_service),
) -> VehicleRoutingResult:
    try:
        result = solver.solve(request)
    except RoutingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    storage.save_routing_plan(request, result)
    return result


@router.get("/plans/{plan_id}", response_model=VehicleRoutingResult)
def get_plan(plan_id: str, storage: SQLiteStorageService = Depends(get_storage_service)) -> VehicleRoutingResult:
    pair = storage.get_routing_plan(plan_id)
    if pair is None:
        raise HTTPException(status_code=404, detail=f"Routing plan {plan_id} not found")
    return pair[1]
