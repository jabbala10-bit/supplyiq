"""Unit tests for src/services/routing/heuristic_router.py (pure Python, no ortools needed)."""
from __future__ import annotations

from src.domain.routing_schemas import SolveMethod
from src.services.routing.heuristic_router import GreedyNearestNeighborRouter


class TestGreedyRouter:
    def test_all_stops_assigned_when_capacity_sufficient(self, sample_routing_request):
        router = GreedyNearestNeighborRouter()
        result = router.solve(sample_routing_request)
        assert result.all_stops_assigned is True
        assert result.solve_method == SolveMethod.HEURISTIC

    def test_visits_nearest_stop_first(self, sample_routing_request):
        router = GreedyNearestNeighborRouter()
        result = router.solve(sample_routing_request)
        assert len(result.routes) == 1
        first_stop_id = result.routes[0].steps[0].stop_id
        closest_stop = min(
            sample_routing_request.stops,
            key=lambda s: (s.location.latitude - 40.7128) ** 2 + (s.location.longitude - (-74.0060)) ** 2,
        )
        assert first_stop_id == closest_stop.stop_id

    def test_insufficient_capacity_leaves_stops_unassigned(self, sample_routing_request):
        small_vehicle_request = sample_routing_request.model_copy(
            update={"vehicles": [sample_routing_request.vehicles[0].model_copy(update={"capacity_units": 5})]}
        )
        router = GreedyNearestNeighborRouter()
        result = router.solve(small_vehicle_request)
        assert len(result.unassigned_stop_ids) > 0

    def test_multiple_vehicles_split_stops(self, sample_routing_request):
        two_vehicle_request = sample_routing_request.model_copy(
            update={
                "vehicles": [
                    sample_routing_request.vehicles[0].model_copy(update={"vehicle_id": "V1", "capacity_units": 8}),
                    sample_routing_request.vehicles[0].model_copy(update={"vehicle_id": "V2", "capacity_units": 8}),
                ]
            }
        )
        router = GreedyNearestNeighborRouter()
        result = router.solve(two_vehicle_request)
        assert result.all_stops_assigned is True
        assert len(result.routes) <= 2

    def test_total_distance_is_non_negative(self, sample_routing_request):
        router = GreedyNearestNeighborRouter()
        result = router.solve(sample_routing_request)
        assert result.total_distance_km >= 0

    def test_load_utilization_within_bounds(self, sample_routing_request):
        router = GreedyNearestNeighborRouter()
        result = router.solve(sample_routing_request)
        for route in result.routes:
            assert 0 <= route.load_utilization_pct <= 100
