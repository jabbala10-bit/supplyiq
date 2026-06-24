"""Shared pytest fixtures for SupplyIQ tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.config.settings import Settings
from src.domain.network_schemas import DemandLocation, NetworkOptimizationRequest, ShippingLane, Warehouse
from src.domain.replenishment_schemas import ReplenishmentPlanRequest, SKULocation
from src.domain.routing_schemas import DeliveryStop, GeoPoint, Vehicle, VehicleRoutingRequest


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test_supplyiq.db")


@pytest.fixture
def test_settings(tmp_path: Path, tmp_db_path: str) -> Settings:
    return Settings(
        environment="development",
        sqlite_path=tmp_db_path,
        exact_solve_time_limit_seconds=3.0,
        routing_exact_max_stops=20,
        network_exact_max_variables=500,
    )


@pytest.fixture
def sample_sku_location() -> SKULocation:
    return SKULocation(
        sku="SKU-001", location_id="WH-EAST", current_stock=120, daily_demand_forecast=25.0,
        demand_std_dev=5.0, lead_time_days=7, unit_cost=12.50, holding_cost_rate=0.2,
        order_cost=75.0, service_level_target=0.95,
    )


@pytest.fixture
def low_stock_sku_location() -> SKULocation:
    return SKULocation(
        sku="SKU-002", location_id="WH-EAST", current_stock=5, daily_demand_forecast=10.0,
        demand_std_dev=3.0, lead_time_days=14, unit_cost=40.0, holding_cost_rate=0.25,
        order_cost=120.0, service_level_target=0.99,
    )


@pytest.fixture
def sample_replenishment_request(sample_sku_location, low_stock_sku_location) -> ReplenishmentPlanRequest:
    return ReplenishmentPlanRequest(sku_locations=[sample_sku_location, low_stock_sku_location])


@pytest.fixture
def sample_routing_request() -> VehicleRoutingRequest:
    return VehicleRoutingRequest(
        depot=GeoPoint(latitude=40.7128, longitude=-74.0060),
        stops=[
            DeliveryStop(location=GeoPoint(latitude=40.73, longitude=-73.99), demand_units=5),
            DeliveryStop(location=GeoPoint(latitude=40.75, longitude=-73.97), demand_units=8),
            DeliveryStop(location=GeoPoint(latitude=40.71, longitude=-74.02), demand_units=3),
        ],
        vehicles=[
            Vehicle(vehicle_id="V1", capacity_units=20, start_location=GeoPoint(latitude=40.7128, longitude=-74.0060))
        ],
        average_speed_kmh=35.0,
    )


@pytest.fixture
def sample_network_request() -> NetworkOptimizationRequest:
    return NetworkOptimizationRequest(
        warehouses=[
            Warehouse(warehouse_id="WH-1", capacity_units=500),
            Warehouse(warehouse_id="WH-2", capacity_units=300),
        ],
        demand_locations=[
            DemandLocation(location_id="L1", demand_units=400),
            DemandLocation(location_id="L2", demand_units=200),
        ],
        shipping_lanes=[
            ShippingLane(warehouse_id="WH-1", location_id="L1", cost_per_unit=2.0),
            ShippingLane(warehouse_id="WH-1", location_id="L2", cost_per_unit=3.5),
            ShippingLane(warehouse_id="WH-2", location_id="L1", cost_per_unit=1.5),
            ShippingLane(warehouse_id="WH-2", location_id="L2", cost_per_unit=2.5),
        ],
    )
