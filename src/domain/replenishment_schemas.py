"""
Domain schemas for SupplyIQ's replenishment/demand-forecasting domain.

Pure Pydantic models — no OR-Tools, no FastAPI imports here. The
ReplenishmentSolver operates on these types and returns these types.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class SolveMethod(str, Enum):
    """Shared across all three optimization domains (ADR-001)."""

    EXACT = "exact"          # OR-Tools LP/MIP/CP-SAT solved to optimality (or proven-optimal-enough gap)
    HEURISTIC = "heuristic"  # fallback used when problem size/time exceeds the exact-solve budget


class SKULocation(BaseModel):
    """A single SKU at a single location — the unit of replenishment planning."""

    sku: str
    location_id: str
    current_stock: int = Field(ge=0)
    daily_demand_forecast: float = Field(gt=0, description="Mean forecasted daily demand")
    demand_std_dev: float = Field(ge=0, description="Std dev of daily demand, for safety stock calc")
    lead_time_days: int = Field(gt=0, description="Days between placing and receiving a reorder")
    unit_cost: float = Field(gt=0)
    holding_cost_rate: float = Field(gt=0, description="Annual holding cost as a fraction of unit cost")
    order_cost: float = Field(ge=0, description="Fixed cost per reorder placed, independent of quantity")
    service_level_target: float = Field(default=0.95, ge=0.5, le=0.999)
    max_capacity: Optional[int] = Field(default=None, ge=0)


class ReplenishmentRecommendation(BaseModel):
    """The output of replenishment planning for a single SKU/location."""

    sku: str
    location_id: str
    reorder_point: float
    safety_stock: float
    economic_order_quantity: float
    recommended_order_quantity: int
    should_reorder_now: bool
    days_of_supply_remaining: float
    solve_method: SolveMethod
    reasoning: list[str] = Field(default_factory=list)


class ReplenishmentPlanRequest(BaseModel):
    sku_locations: list[SKULocation] = Field(min_length=1)
    budget_constraint: Optional[float] = Field(default=None, gt=0, description="Total spend cap across all reorders this cycle")


class ReplenishmentPlanResult(BaseModel):
    plan_id: str = Field(default_factory=_new_id)
    recommendations: list[ReplenishmentRecommendation] = Field(default_factory=list)
    total_order_cost: float = 0.0
    budget_constraint_binding: bool = False
    solve_method: SolveMethod
    solve_time_seconds: float = 0.0
    created_at: datetime = Field(default_factory=_utcnow)
