"""
Integration tests for CopilotOrchestrator: real SQLite storage, real
heuristic solvers (network/routing greedy fallbacks — no ortools
needed), with the LLM call mocked via httpx.MockTransport. Exercises
the full ask -> modify -> re-solve -> persist flow end to end.
"""
from __future__ import annotations

import json

import httpx
import pytest

from src.domain.copilot_schemas import CopilotIntent, CopilotQuery, OptimizationDomain
from src.services.copilot.copilot_service import CopilotService
from src.services.copilot.orchestrator import CopilotOrchestrator
from src.services.network.greedy_allocator import GreedyCostAllocator
from src.services.network.network_solver import NetworkOptimizationSolver
from src.services.replenishment.replenishment_solver import ReplenishmentSolver
from src.services.routing.heuristic_router import GreedyNearestNeighborRouter
from src.services.routing.vrp_solver import VehicleRoutingSolver
from src.services.storage.sqlite_service import SQLiteStorageService


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://localhost:11434")


class FakeNetworkSolver(NetworkOptimizationSolver):
    """
    Forces the heuristic path so this integration test never needs
    ortools — same approach as deferred-import tests elsewhere in this
    portfolio: exercise real orchestration logic, fake only the heavy
    native-dependency boundary.
    """

    def solve(self, request):
        return GreedyCostAllocator().solve(request)


class FakeRoutingSolver(VehicleRoutingSolver):
    def solve(self, request):
        return GreedyNearestNeighborRouter().solve(request)


@pytest.fixture
def storage(test_settings) -> SQLiteStorageService:
    return SQLiteStorageService(test_settings)


@pytest.fixture
def orchestrator_factory(test_settings, storage):
    def _build(llm_handler):
        copilot = CopilotService(test_settings, client=_mock_client(llm_handler), storage=storage)
        return CopilotOrchestrator(
            copilot=copilot,
            replenishment_solver=ReplenishmentSolver(test_settings),
            routing_solver=FakeRoutingSolver(test_settings),
            network_solver=FakeNetworkSolver(test_settings),
            storage=storage,
        )

    return _build


class TestExplainFlow:
    def test_explain_does_not_trigger_resolve(self, orchestrator_factory, storage, sample_network_request):
        result = GreedyCostAllocator().solve(sample_network_request)
        storage.save_network_plan(sample_network_request, result)

        def handler(request):
            return httpx.Response(
                200,
                json={
                    "response": json.dumps(
                        {"intent": "explain", "answer_text": "Because it's cheapest.", "modifications": []}
                    )
                },
            )

        orchestrator = orchestrator_factory(handler)
        query = CopilotQuery(question="why WH-2?", plan_id=result.plan_id, domain=OptimizationDomain.NETWORK)
        response = orchestrator.handle_query(query)

        assert response.intent == CopilotIntent.EXPLAIN
        assert response.new_plan_id is None
        assert storage.count_plans() == 1


class TestWhatIfFlow:
    def test_what_if_closing_warehouse_triggers_resolve(self, orchestrator_factory, storage, sample_network_request):
        result = GreedyCostAllocator().solve(sample_network_request)
        storage.save_network_plan(sample_network_request, result)

        def handler(request):
            return httpx.Response(
                200,
                json={
                    "response": json.dumps(
                        {
                            "intent": "what_if", "answer_text": "Testing WH-1 closure.",
                            "modifications": [
                                {
                                    "field_path": "warehouses[WH-1].is_active", "new_value": "false",
                                    "rationale": "user request",
                                }
                            ],
                        }
                    )
                },
            )

        orchestrator = orchestrator_factory(handler)
        query = CopilotQuery(
            question="what if we close WH-1?", plan_id=result.plan_id, domain=OptimizationDomain.NETWORK
        )
        response = orchestrator.handle_query(query)

        assert response.intent == CopilotIntent.WHAT_IF
        assert response.new_plan_id is not None
        assert response.new_plan_id != result.plan_id

        new_pair = storage.get_network_plan(response.new_plan_id)
        assert new_pair is not None
        new_request, new_result = new_pair
        wh1 = next(w for w in new_request.warehouses if w.warehouse_id == "WH-1")
        assert wh1.is_active is False
        assert new_result.unmet_demand_units > 0 or new_result.total_cost != result.total_cost

    def test_what_if_on_routing_plan(self, orchestrator_factory, storage, sample_routing_request):
        result = GreedyNearestNeighborRouter().solve(sample_routing_request)
        storage.save_routing_plan(sample_routing_request, result)

        def handler(request):
            return httpx.Response(
                200,
                json={
                    "response": json.dumps(
                        {
                            "intent": "what_if", "answer_text": "Testing higher vehicle capacity.",
                            "modifications": [
                                {
                                    "field_path": "vehicles[V1].capacity_units", "new_value": "100",
                                    "rationale": "user request",
                                }
                            ],
                        }
                    )
                },
            )

        orchestrator = orchestrator_factory(handler)
        query = CopilotQuery(
            question="what if V1 had more capacity?", plan_id=result.plan_id, domain=OptimizationDomain.ROUTING
        )
        response = orchestrator.handle_query(query)

        assert response.new_plan_id is not None
        new_pair = storage.get_routing_plan(response.new_plan_id)
        assert new_pair[0].vehicles[0].capacity_units == 100

    def test_what_if_on_replenishment_budget(self, orchestrator_factory, storage, sample_replenishment_request):
        result = ReplenishmentSolver().solve(sample_replenishment_request)
        storage.save_replenishment_plan(sample_replenishment_request, result)

        def handler(request):
            return httpx.Response(
                200,
                json={
                    "response": json.dumps(
                        {
                            "intent": "what_if", "answer_text": "Testing a $100 budget cap.",
                            "modifications": [
                                {
                                    "field_path": "budget_constraint", "new_value": "100",
                                    "rationale": "user requested a tight budget",
                                }
                            ],
                        }
                    )
                },
            )

        orchestrator = orchestrator_factory(handler)
        query = CopilotQuery(
            question="what if we only had $100?", plan_id=result.plan_id, domain=OptimizationDomain.REPLENISHMENT
        )
        response = orchestrator.handle_query(query)

        assert response.new_plan_id is not None
        new_pair = storage.get_replenishment_plan(response.new_plan_id)
        assert new_pair[0].budget_constraint == 100.0
