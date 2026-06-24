"""Unit tests for src/services/replenishment/replenishment_solver.py."""
from __future__ import annotations

from src.services.replenishment.replenishment_solver import ReplenishmentSolver, _z_score


class TestZScore:
    def test_known_service_levels_return_exact_values(self):
        assert _z_score(0.95) == 1.65
        assert _z_score(0.99) == 2.33

    def test_interpolation_between_known_levels(self):
        z = _z_score(0.925)
        assert abs(z - 1.465) < 1e-9

    def test_above_highest_known_level_returns_highest(self):
        assert _z_score(0.9999) == _z_score(0.999)


class TestRecommendForSKU:
    def test_safety_stock_and_reorder_point_formula(self, test_settings, sample_sku_location):
        solver = ReplenishmentSolver(test_settings)
        rec = solver._recommend_for_sku(sample_sku_location)
        assert abs(rec.safety_stock - 21.83) < 0.1
        assert abs(rec.reorder_point - 196.83) < 0.1

    def test_should_reorder_when_stock_below_reorder_point(self, test_settings, low_stock_sku_location):
        solver = ReplenishmentSolver(test_settings)
        rec = solver._recommend_for_sku(low_stock_sku_location)
        assert rec.should_reorder_now is True
        assert rec.recommended_order_quantity > 0

    def test_should_not_reorder_when_stock_high(self, test_settings, sample_sku_location):
        high_stock = sample_sku_location.model_copy(update={"current_stock": 100000})
        solver = ReplenishmentSolver(test_settings)
        rec = solver._recommend_for_sku(high_stock)
        assert rec.should_reorder_now is False
        assert rec.recommended_order_quantity == 0

    def test_eoq_respects_max_capacity(self, test_settings, sample_sku_location):
        capped = sample_sku_location.model_copy(update={"max_capacity": 130, "current_stock": 120})
        solver = ReplenishmentSolver(test_settings)
        rec = solver._recommend_for_sku(capped)
        assert rec.economic_order_quantity <= 10

    def test_days_of_supply_calculation(self, test_settings, low_stock_sku_location):
        solver = ReplenishmentSolver(test_settings)
        rec = solver._recommend_for_sku(low_stock_sku_location)
        assert abs(rec.days_of_supply_remaining - 0.5) < 0.01

    def test_low_stock_flags_urgency_in_reasoning(self, test_settings, low_stock_sku_location):
        solver = ReplenishmentSolver(test_settings)
        rec = solver._recommend_for_sku(low_stock_sku_location)
        assert any("urgency" in r.lower() or "days" in r.lower() for r in rec.reasoning)


class TestSolve:
    def test_solve_produces_one_recommendation_per_sku(self, test_settings, sample_replenishment_request):
        solver = ReplenishmentSolver(test_settings)
        result = solver.solve(sample_replenishment_request)
        assert len(result.recommendations) == len(sample_replenishment_request.sku_locations)

    def test_solve_without_budget_constraint_not_binding(self, test_settings, sample_replenishment_request):
        solver = ReplenishmentSolver(test_settings)
        result = solver.solve(sample_replenishment_request)
        assert result.budget_constraint_binding is False

    def test_solve_with_generous_budget_not_binding(self, test_settings, sample_replenishment_request):
        request = sample_replenishment_request.model_copy(update={"budget_constraint": 1_000_000.0})
        solver = ReplenishmentSolver(test_settings)
        result = solver.solve(request)
        assert result.budget_constraint_binding is False

    def test_total_order_cost_matches_recommendations(self, test_settings, sample_replenishment_request):
        solver = ReplenishmentSolver(test_settings)
        result = solver.solve(sample_replenishment_request)
        cost_by_sku = {sl.sku: sl.unit_cost for sl in sample_replenishment_request.sku_locations}
        expected = sum(r.recommended_order_quantity * cost_by_sku[r.sku] for r in result.recommendations)
        assert abs(result.total_order_cost - expected) < 0.01
