"""Unit tests for src/services/copilot/copilot_service.py."""
from __future__ import annotations

import json

import httpx
import pytest

from src.domain.copilot_schemas import CopilotIntent, CopilotQuery, OptimizationDomain
from src.domain.exceptions import IntentClassificationError, LLMUnavailableError, PlanNotFoundError
from src.services.copilot.copilot_service import CopilotService
from src.services.storage.sqlite_service import SQLiteStorageService


def _mock_transport(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://localhost:11434")


EXPLAIN_RESPONSE = {
    "intent": "explain", "answer_text": "SKU-002 needs reordering because stock is below the reorder point.",
    "modifications": [],
}

WHAT_IF_RESPONSE = {
    "intent": "what_if", "answer_text": "Testing closing WH-1.",
    "modifications": [
        {"field_path": "warehouses[WH-1].is_active", "new_value": "false", "rationale": "user asked to close WH-1"}
    ],
}


@pytest.fixture
def storage(test_settings) -> SQLiteStorageService:
    return SQLiteStorageService(test_settings)


class TestHealthCheck:
    def test_health_check_true_on_200(self, test_settings, storage):
        def handler(request):
            return httpx.Response(200, json={"models": []})

        service = CopilotService(test_settings, client=_mock_transport(handler), storage=storage)
        assert service.health_check() is True

    def test_health_check_false_on_connection_error(self, test_settings, storage):
        def handler(request):
            raise httpx.ConnectError("refused")

        service = CopilotService(test_settings, client=_mock_transport(handler), storage=storage)
        assert service.health_check() is False


class TestAsk:
    def test_plan_not_found_raises(self, test_settings, storage):
        def handler(request):
            return httpx.Response(200, json={"response": json.dumps(EXPLAIN_RESPONSE)})

        service = CopilotService(test_settings, client=_mock_transport(handler), storage=storage)
        query = CopilotQuery(question="why?", plan_id="missing-plan", domain=OptimizationDomain.NETWORK)
        with pytest.raises(PlanNotFoundError):
            service.ask(query)

    def test_explain_intent_returns_grounded_answer(self, test_settings, storage, sample_network_request):
        from src.services.network.greedy_allocator import GreedyCostAllocator

        result = GreedyCostAllocator().solve(sample_network_request)
        storage.save_network_plan(sample_network_request, result)

        def handler(request):
            return httpx.Response(200, json={"response": json.dumps(EXPLAIN_RESPONSE)})

        service = CopilotService(test_settings, client=_mock_transport(handler), storage=storage)
        query = CopilotQuery(
            question="why these allocations?", plan_id=result.plan_id, domain=OptimizationDomain.NETWORK
        )
        response = service.ask(query)

        assert response.intent == CopilotIntent.EXPLAIN
        assert len(response.answer_text) > 0

    def test_what_if_intent_returns_modifications(self, test_settings, storage, sample_network_request):
        from src.services.network.greedy_allocator import GreedyCostAllocator

        result = GreedyCostAllocator().solve(sample_network_request)
        storage.save_network_plan(sample_network_request, result)

        def handler(request):
            return httpx.Response(200, json={"response": json.dumps(WHAT_IF_RESPONSE)})

        service = CopilotService(test_settings, client=_mock_transport(handler), storage=storage)
        query = CopilotQuery(
            question="what if we close WH-1?", plan_id=result.plan_id, domain=OptimizationDomain.NETWORK
        )
        response = service.ask(query)

        assert response.intent == CopilotIntent.WHAT_IF
        assert len(response.modifications_applied) == 1
        assert response.modifications_applied[0].field_path == "warehouses[WH-1].is_active"

    def test_connection_error_raises_llm_unavailable(self, test_settings, storage, sample_network_request):
        from src.services.network.greedy_allocator import GreedyCostAllocator

        result = GreedyCostAllocator().solve(sample_network_request)
        storage.save_network_plan(sample_network_request, result)

        def handler(request):
            raise httpx.ConnectError("refused")

        service = CopilotService(test_settings, client=_mock_transport(handler), storage=storage)
        query = CopilotQuery(question="why?", plan_id=result.plan_id, domain=OptimizationDomain.NETWORK)
        with pytest.raises(LLMUnavailableError):
            service.ask(query)

    def test_malformed_response_retries_then_raises(self, test_settings, storage, sample_network_request):
        from src.services.network.greedy_allocator import GreedyCostAllocator

        result = GreedyCostAllocator().solve(sample_network_request)
        storage.save_network_plan(sample_network_request, result)

        call_count = {"n": 0}

        def handler(request):
            call_count["n"] += 1
            return httpx.Response(200, json={"response": "not valid json {{{"})

        service = CopilotService(test_settings, client=_mock_transport(handler), storage=storage)
        query = CopilotQuery(question="why?", plan_id=result.plan_id, domain=OptimizationDomain.NETWORK)
        with pytest.raises(IntentClassificationError):
            service.ask(query)
        assert call_count["n"] == 3

    def test_recovers_after_one_bad_attempt(self, test_settings, storage, sample_network_request):
        from src.services.network.greedy_allocator import GreedyCostAllocator

        result = GreedyCostAllocator().solve(sample_network_request)
        storage.save_network_plan(sample_network_request, result)

        call_count = {"n": 0}

        def handler(request):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return httpx.Response(200, json={"response": "{bad"})
            return httpx.Response(200, json={"response": json.dumps(EXPLAIN_RESPONSE)})

        service = CopilotService(test_settings, client=_mock_transport(handler), storage=storage)
        query = CopilotQuery(question="why?", plan_id=result.plan_id, domain=OptimizationDomain.NETWORK)
        response = service.ask(query)
        assert response.intent == CopilotIntent.EXPLAIN
        assert call_count["n"] == 2
