"""
Domain schemas for SupplyIQ's multi-echelon network-optimization domain:
deciding how much to ship from which warehouses to which demand
locations at minimum cost, subject to warehouse capacity and demand
satisfaction — the classic transportation/facility-flow LP formulation.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from src.domain.replenishment_schemas import SolveMethod


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class Warehouse(BaseModel):
    warehouse_id: str
    capacity_units: int = Field(gt=0)
    fixed_operating_cost: float = Field(default=0.0, ge=0, description="Cost incurred only if this warehouse ships anything")
    is_active: bool = True


class DemandLocation(BaseModel):
    location_id: str
    demand_units: int = Field(gt=0)


class ShippingLane(BaseModel):
    """The cost to ship one unit from a given warehouse to a given demand location."""

    warehouse_id: str
    location_id: str
    cost_per_unit: float = Field(ge=0)
    max_capacity_units: Optional[int] = Field(default=None, ge=0, description="Lane-specific shipping cap, if any")


class NetworkOptimizationRequest(BaseModel):
    warehouses: list[Warehouse] = Field(min_length=1)
    demand_locations: list[DemandLocation] = Field(min_length=1)
    shipping_lanes: list[ShippingLane] = Field(min_length=1)
    allow_unmet_demand: bool = Field(
        default=False, description="If true, unmet demand is penalized rather than making the problem infeasible"
    )
    unmet_demand_penalty_per_unit: float = Field(default=1_000_000.0, ge=0)


class ShipmentAllocation(BaseModel):
    warehouse_id: str
    location_id: str
    units_shipped: int
    cost: float


class NetworkOptimizationResult(BaseModel):
    plan_id: str = Field(default_factory=_new_id)
    allocations: list[ShipmentAllocation] = Field(default_factory=list)
    total_cost: float = 0.0
    unmet_demand_units: int = 0
    active_warehouse_ids: list[str] = Field(default_factory=list)
    solve_method: SolveMethod = SolveMethod.EXACT
    is_feasible: bool = True
    solve_time_seconds: float = 0.0
    created_at: datetime = Field(default_factory=_utcnow)
