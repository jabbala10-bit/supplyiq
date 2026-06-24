"""Unit tests for src/services/network/greedy_allocator.py (pure Python, no ortools needed)."""
from __future__ import annotations

from src.domain.network_schemas import SolveMethod
from src.services.network.greedy_allocator import GreedyCostAllocator


class TestGreedyAllocator:
    def test_demand_fully_met_when_capacity_sufficient(self, sample_network_request):
        allocator = GreedyCostAllocator()
        result = allocator.solve(sample_network_request)
        assert result.unmet_demand_units == 0
        assert result.is_feasible is True
        assert result.solve_method == SolveMethod.HEURISTIC

    def test_prefers_cheaper_lane(self, sample_network_request):
        allocator = GreedyCostAllocator()
        result = allocator.solve(sample_network_request)
        l1_allocations = [a for a in result.allocations if a.location_id == "L1"]
        wh2_alloc = next((a for a in l1_allocations if a.warehouse_id == "WH-2"), None)
        assert wh2_alloc is not None
        assert wh2_alloc.units_shipped == 300

    def test_total_cost_matches_allocations(self, sample_network_request):
        allocator = GreedyCostAllocator()
        result = allocator.solve(sample_network_request)
        expected = sum(a.cost for a in result.allocations)
        assert abs(result.total_cost - expected) < 0.01

    def test_insufficient_capacity_produces_unmet_demand(self, sample_network_request):
        constrained = sample_network_request.model_copy(
            update={
                "warehouses": [w.model_copy(update={"capacity_units": 10}) for w in sample_network_request.warehouses]
            }
        )
        allocator = GreedyCostAllocator()
        result = allocator.solve(constrained)
        assert result.unmet_demand_units > 0
        assert result.is_feasible is False

    def test_allow_unmet_demand_marks_feasible_despite_shortfall(self, sample_network_request):
        constrained = sample_network_request.model_copy(
            update={
                "warehouses": [w.model_copy(update={"capacity_units": 10}) for w in sample_network_request.warehouses],
                "allow_unmet_demand": True,
            }
        )
        allocator = GreedyCostAllocator()
        result = allocator.solve(constrained)
        assert result.unmet_demand_units > 0
        assert result.is_feasible is True

    def test_inactive_warehouse_excluded(self, sample_network_request):
        with_inactive = sample_network_request.model_copy(
            update={
                "warehouses": [
                    sample_network_request.warehouses[0],
                    sample_network_request.warehouses[1].model_copy(update={"is_active": False}),
                ],
                "allow_unmet_demand": True,
            }
        )
        allocator = GreedyCostAllocator()
        result = allocator.solve(with_inactive)
        assert "WH-2" not in result.active_warehouse_ids

    def test_lane_capacity_cap_respected(self, sample_network_request):
        capped = sample_network_request.model_copy(
            update={
                "shipping_lanes": [
                    lane.model_copy(update={"max_capacity_units": 50})
                    if lane.warehouse_id == "WH-2" and lane.location_id == "L1"
                    else lane
                    for lane in sample_network_request.shipping_lanes
                ]
            }
        )
        allocator = GreedyCostAllocator()
        result = allocator.solve(capped)
        wh2_l1 = next((a for a in result.allocations if a.warehouse_id == "WH-2" and a.location_id == "L1"), None)
        if wh2_l1:
            assert wh2_l1.units_shipped <= 50
