"""
End-to-end test: solve a network optimization plan, ask the copilot to
explain it, then ask a what-if question that triggers a real re-solve --
through the actual FastAPI app, with only the LLM call mocked.
"""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from src.api import dependencies as deps
from src.api.main import app
from src.services.copilot.copilot_service import CopilotService
from src.services.copilot.orchestrator import CopilotOrchestrator
from src.services.network.greedy_allocator import GreedyCostAllocator
from src.services.network.network_solver import NetworkOptimizationSolver
from src.services.replenishment.replenishment_solver import ReplenishmentSolver
from src.services.routing.heuristic_router import GreedyNearestNeighborRouter
from src.services.routing.vrp_solver import VehicleRoutingSolver
from src.services.storage.sqlite_service import SQLiteStorageService

_NETWORK_PAYLOAD = {
    "warehouses": [
        {"warehouse_id": "WH-1", "capacity_units": 500},
        {"warehouse_id": "WH-2", "capacity_units": 300},
    ],
    "demand_locations": [
        {"location_id": "L1", "demand_units": 400},
        {"location_id": "L2", "demand_units": 200},
    ],
    "shipping_lanes": [
        {"warehouse_id": "WH-1", "location_id": "L1", "cost_per_unit": 2.0},
        {"warehouse_id": "WH-1", "location_id": "L2", "cost_per_unit": 3.5},
        {"warehouse_id": "WH-2", "location_id": "L1", "cost_per_unit": 1.5},
        {"warehouse_id": "WH-2", "location_id": "L2", "cost_per_unit": 2.5},
    ],
}


class FakeNetworkSolver(NetworkOptimizationSolver):
    def solve(self, request):
        return GreedyCostAllocator().solve(request)


class FakeRoutingSolver(VehicleRoutingSolver):
    def solve(self, request):
        return GreedyNearestNeighborRouter().solve(request)


def _llm_handler_factory():
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            body = {
                "intent": "explain",
                "answer_text": "WH-2 ships to L1 because it has the lowest cost-per-unit lane to that location.",
                "modifications": [],
            }
        else:
            body = {
                "intent": "what_if",
                "answer_text": "Testing what happens if WH-1 is closed.",
                "modifications": [
                    {
                        "field_path": "warehouses[WH-1].is_active", "new_value": "false",
                        "rationale": "user asked to close WH-1",
                    }
                ],
            }
        return httpx.Response(200, json={"response": json.dumps(body)})

    return handler


@pytest.fixture
def e2e_client(test_settings):
    storage = SQLiteStorageService(test_settings)
    llm_client = httpx.Client(
        transport=httpx.MockTransport(_llm_handler_factory()), base_url=test_settings.ollama_base_url
    )
    copilot = CopilotService(test_settings, client=llm_client, storage=storage)
    orchestrator = CopilotOrchestrator(
        copilot=copilot,
        replenishment_solver=ReplenishmentSolver(test_settings),
        routing_solver=FakeRoutingSolver(test_settings),
        network_solver=FakeNetworkSolver(test_settings),
        storage=storage,
    )

    app.dependency_overrides[deps.get_settings] = lambda: test_settings
    app.dependency_overrides[deps.get_storage_service] = lambda: storage
    app.dependency_overrides[deps.get_network_solver] = lambda: FakeNetworkSolver(test_settings)
    app.dependency_overrides[deps.get_copilot_orchestrator] = lambda: orchestrator

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


class TestFullCopilotJourney:
    def test_solve_explain_then_what_if(self, e2e_client):
        solve_resp = e2e_client.post("/network/solve", json=_NETWORK_PAYLOAD)
        assert solve_resp.status_code == 201
        plan = solve_resp.json()
        plan_id = plan["plan_id"]
        assert plan["unmet_demand_units"] == 0

        explain_resp = e2e_client.post(
            "/copilot/ask",
            json={"question": "why does WH-2 ship to L1?", "plan_id": plan_id, "domain": "network"},
        )
        assert explain_resp.status_code == 200
        explain_body = explain_resp.json()
        assert explain_body["intent"] == "explain"
        assert explain_body["new_plan_id"] is None

        whatif_resp = e2e_client.post(
            "/copilot/ask",
            json={"question": "what if we close WH-1?", "plan_id": plan_id, "domain": "network"},
        )
        assert whatif_resp.status_code == 200
        whatif_body = whatif_resp.json()
        assert whatif_body["intent"] == "what_if"
        new_plan_id = whatif_body["new_plan_id"]
        assert new_plan_id is not None
        assert new_plan_id != plan_id

        new_plan_resp = e2e_client.get(f"/network/plans/{new_plan_id}")
        assert new_plan_resp.status_code == 200
        new_plan = new_plan_resp.json()
        assert new_plan["unmet_demand_units"] == 300
        assert "WH-1" not in new_plan["active_warehouse_ids"]

    def test_copilot_on_missing_plan_returns_404(self, e2e_client):
        resp = e2e_client.post(
            "/copilot/ask",
            json={"question": "why?", "plan_id": "does-not-exist", "domain": "network"},
        )
        assert resp.status_code == 404
