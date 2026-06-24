"""
Domain schemas for SupplyIQ's last-mile vehicle-routing domain.

These map closely to OR-Tools' routing solver's native concepts
(depot, vehicles, time windows, capacities) so the solver layer can
translate directly without an awkward impedance mismatch.
"""
from __future__ import annotations

import uuid
from datetime import datetime, time, timezone
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from src.domain.replenishment_schemas import SolveMethod


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class GeoPoint(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class DeliveryStop(BaseModel):
    """A single delivery destination to be visited by exactly one vehicle."""

    stop_id: str = Field(default_factory=_new_id)
    location: GeoPoint
    demand_units: int = Field(gt=0, description="Capacity consumed on the vehicle, e.g. package count or weight")
    time_window_start: Optional[time] = None
    time_window_end: Optional[time] = None
    service_duration_minutes: int = Field(default=5, ge=0)

    @field_validator("time_window_end")
    @classmethod
    def _end_after_start(cls, v: Optional[time], info) -> Optional[time]:
        start = info.data.get("time_window_start")
        if v is not None and start is not None and v <= start:
            raise ValueError("time_window_end must be after time_window_start")
        return v


class Vehicle(BaseModel):
    vehicle_id: str
    capacity_units: int = Field(gt=0)
    start_location: GeoPoint
    max_route_duration_minutes: int = Field(default=480, gt=0)


class VehicleRoutingRequest(BaseModel):
    depot: GeoPoint
    stops: list[DeliveryStop] = Field(min_length=1)
    vehicles: list[Vehicle] = Field(min_length=1)
    average_speed_kmh: float = Field(default=40.0, gt=0)


class RouteStep(BaseModel):
    stop_id: str
    arrival_time_minutes: float
    departure_time_minutes: float
    cumulative_load: int


class VehicleRoute(BaseModel):
    vehicle_id: str
    steps: list[RouteStep] = Field(default_factory=list)
    total_distance_km: float = 0.0
    total_duration_minutes: float = 0.0
    load_utilization_pct: float = 0.0


class VehicleRoutingResult(BaseModel):
    plan_id: str = Field(default_factory=_new_id)
    routes: list[VehicleRoute] = Field(default_factory=list)
    unassigned_stop_ids: list[str] = Field(default_factory=list)
    total_distance_km: float = 0.0
    solve_method: SolveMethod = SolveMethod.EXACT
    solve_time_seconds: float = 0.0
    created_at: datetime = Field(default_factory=_utcnow)

    @property
    def all_stops_assigned(self) -> bool:
        return len(self.unassigned_stop_ids) == 0
