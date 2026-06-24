"""
Integration tests for the FastAPI application using TestClient with
dependency overrides — network/routing solvers forced to their
heuristic paths so these tests never need ortools installed.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api import dependencies as deps
from src.api.main import app
from src.services.network.greedy_allocator import GreedyCostAllocator
from src.services.network.network_solver import NetworkOptimizationSolver
from src.services.replenishment.replenishment_solver import ReplenishmentSolver
from src.services.routing.heuristic_router import GreedyNearestNeighborRouter
from src.services.routing.vrp_solver import VehicleRoutingSolver
from src.services.storage.sqlite_service import SQLiteStorageService


class FakeNetworkSolver(NetworkOptimizationSolver):
    def solve(self, request):
        return GreedyCostAllocator().solve(request)


class FakeRoutingSolver(VehicleRoutingSolver):
    def solve(self, request):
        return GreedyNearestNeighborRouter().solve(request)


@pytest.fixture
def client(test_settings):
    storage = SQLiteStorageService(test_settings)

    app.dependency_overrides[deps.get_settings] = lambda: test_settings
    app.dependency_overrides[deps.get_storage_service] = lambda: storage
    app.dependency_overrides[deps.get_replenishment_solver] = lambda: ReplenishmentSolver(test_settings)
    app.dependency_overrides[deps.get_routing_solver] = lambda: FakeRoutingSolver(test_settings)
    app.dependency_overrides[deps.get_network_solver] = lambda: FakeNetworkSolver(test_settings)

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


class TestHealthRoutes:
    def test_health_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200


class TestReplenishmentRoutes:
    def test_solve_and_fetch_plan(self, client, sample_replenishment_request):
        payload = sample_replenishment_request.model_dump(mode="json")
        resp = client.post("/replenishment/solve", json=payload)
        assert resp.status_code == 201
        plan_id = resp.json()["plan_id"]

        get_resp = client.get(f"/replenishment/plans/{plan_id}")
        assert get_resp.status_code == 200

    def test_get_nonexistent_plan_404(self, client):
        resp = client.get("/replenishment/plans/missing")
        assert resp.status_code == 404


class TestRoutingRoutes:
    def test_solve_and_fetch_plan(self, client, sample_routing_request):
        payload = sample_routing_request.model_dump(mode="json")
        resp = client.post("/routing/solve", json=payload)
        assert resp.status_code == 201
        plan_id = resp.json()["plan_id"]

        get_resp = client.get(f"/routing/plans/{plan_id}")
        assert get_resp.status_code == 200

    def test_insufficient_capacity_returns_422(self, client, sample_routing_request):
        payload = sample_routing_request.model_dump(mode="json")
        payload["vehicles"] = [{**payload["vehicles"][0], "capacity_units": 1}]
        resp = client.post("/routing/solve", json=payload)
        assert resp.status_code == 422


class TestNetworkRoutes:
    def test_solve_and_fetch_plan(self, client, sample_network_request):
        payload = sample_network_request.model_dump(mode="json")
        resp = client.post("/network/solve", json=payload)
        assert resp.status_code == 201
        plan_id = resp.json()["plan_id"]

        get_resp = client.get(f"/network/plans/{plan_id}")
        assert get_resp.status_code == 200

    def test_get_nonexistent_plan_404(self, client):
        resp = client.get("/network/plans/missing")
        assert resp.status_code == 404


class TestMetricsEndpoint:
    def test_metrics_responds(self, client):
        resp = client.get("/metrics")
        assert resp.status_code == 200
