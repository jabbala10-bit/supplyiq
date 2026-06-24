"""Unit tests for src/services/storage/sqlite_service.py."""
from __future__ import annotations

import pytest

from src.services.network.greedy_allocator import GreedyCostAllocator
from src.services.routing.heuristic_router import GreedyNearestNeighborRouter
from src.services.storage.sqlite_service import SQLiteStorageService


@pytest.fixture
def storage(test_settings) -> SQLiteStorageService:
    return SQLiteStorageService(test_settings)


class TestReplenishmentPlanPersistence:
    def test_save_and_get_roundtrip(self, storage, sample_replenishment_request):
        from src.services.replenishment.replenishment_solver import ReplenishmentSolver

        result = ReplenishmentSolver().solve(sample_replenishment_request)
        storage.save_replenishment_plan(sample_replenishment_request, result)

        pair = storage.get_replenishment_plan(result.plan_id)
        assert pair is not None
        fetched_request, fetched_result = pair
        assert len(fetched_request.sku_locations) == len(sample_replenishment_request.sku_locations)
        assert fetched_result.plan_id == result.plan_id

    def test_get_nonexistent_returns_none(self, storage):
        assert storage.get_replenishment_plan("missing") is None


class TestRoutingPlanPersistence:
    def test_save_and_get_roundtrip(self, storage, sample_routing_request):
        result = GreedyNearestNeighborRouter().solve(sample_routing_request)
        storage.save_routing_plan(sample_routing_request, result)

        pair = storage.get_routing_plan(result.plan_id)
        assert pair is not None
        assert pair[1].plan_id == result.plan_id

    def test_get_nonexistent_returns_none(self, storage):
        assert storage.get_routing_plan("missing") is None


class TestNetworkPlanPersistence:
    def test_save_and_get_roundtrip(self, storage, sample_network_request):
        result = GreedyCostAllocator().solve(sample_network_request)
        storage.save_network_plan(sample_network_request, result)

        pair = storage.get_network_plan(result.plan_id)
        assert pair is not None
        assert pair[1].total_cost == result.total_cost

    def test_get_nonexistent_returns_none(self, storage):
        assert storage.get_network_plan("missing") is None


class TestPlanDomainLookup:
    def test_get_plan_domain_returns_correct_domain(self, storage, sample_network_request):
        result = GreedyCostAllocator().solve(sample_network_request)
        storage.save_network_plan(sample_network_request, result)
        assert storage.get_plan_domain(result.plan_id) == "network"

    def test_get_plan_domain_returns_none_for_missing(self, storage):
        assert storage.get_plan_domain("missing") is None


class TestCountPlans:
    def test_count_increases_with_saves(self, storage, sample_network_request, sample_routing_request):
        assert storage.count_plans() == 0
        storage.save_network_plan(sample_network_request, GreedyCostAllocator().solve(sample_network_request))
        storage.save_routing_plan(sample_routing_request, GreedyNearestNeighborRouter().solve(sample_routing_request))
        assert storage.count_plans() == 2
