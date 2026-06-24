"""FastAPI dependency providers for SupplyIQ."""
from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, Header, HTTPException, status

from src.config.settings import Settings, get_settings
from src.domain.exceptions import AuthenticationError
from src.services.copilot.copilot_service import CopilotService
from src.services.copilot.orchestrator import CopilotOrchestrator
from src.services.network.network_solver import NetworkOptimizationSolver
from src.services.replenishment.replenishment_solver import ReplenishmentSolver
from src.services.routing.vrp_solver import VehicleRoutingSolver
from src.services.storage.sqlite_service import SQLiteStorageService


@lru_cache
def get_storage_service() -> SQLiteStorageService:
    return SQLiteStorageService(get_settings())


@lru_cache
def get_replenishment_solver() -> ReplenishmentSolver:
    return ReplenishmentSolver(get_settings())


@lru_cache
def get_routing_solver() -> VehicleRoutingSolver:
    return VehicleRoutingSolver(get_settings())


@lru_cache
def get_network_solver() -> NetworkOptimizationSolver:
    return NetworkOptimizationSolver(get_settings())


@lru_cache
def get_copilot_service() -> CopilotService:
    return CopilotService(get_settings(), storage=get_storage_service())


def get_copilot_orchestrator(
    copilot: CopilotService = Depends(get_copilot_service),
    replenishment: ReplenishmentSolver = Depends(get_replenishment_solver),
    routing: VehicleRoutingSolver = Depends(get_routing_solver),
    network: NetworkOptimizationSolver = Depends(get_network_solver),
    storage: SQLiteStorageService = Depends(get_storage_service),
) -> CopilotOrchestrator:
    return CopilotOrchestrator(copilot, replenishment, routing, network, storage)


def require_api_token(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    if settings.environment == "development":
        return
    if not settings.api_auth_token:
        raise AuthenticationError("Server has no API_AUTH_TOKEN configured.")
    expected = f"Bearer {settings.api_auth_token}"
    if authorization != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing token")
