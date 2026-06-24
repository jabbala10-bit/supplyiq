"""
Unit tests for the budget-constrained LP allocation pass in
ReplenishmentSolver._apply_budget_constraint(). Requires the real
`ortools` package; import-skips gracefully if unavailable.
"""
from __future__ import annotations

import pytest

from src.domain.exceptions import BudgetInfeasibleError
from src.services.replenishment.replenishment_solver import ReplenishmentSolver

pytest.importorskip("ortools", reason="ortools not installed in this environment")


class TestBudgetConstraint:
    def test_tight_budget_reduces_order_quantities(self, test_settings, sample_replenishment_request):
        solver = ReplenishmentSolver(test_settings)
        unconstrained = solver.solve(sample_replenishment_request)

        tight_budget = unconstrained.total_order_cost * 0.5
        request = sample_replenishment_request.model_copy(update={"budget_constraint": tight_budget})
        constrained = solver.solve(request)

        assert constrained.budget_constraint_binding is True
        assert constrained.total_order_cost <= tight_budget + 0.01

    def test_more_urgent_sku_gets_priority_funding(self, test_settings, sample_replenishment_request):
        solver = ReplenishmentSolver(test_settings)
        unconstrained = solver.solve(sample_replenishment_request)
        tight_budget = unconstrained.total_order_cost * 0.3
        request = sample_replenishment_request.model_copy(update={"budget_constraint": tight_budget})
        result = solver.solve(request)

        by_sku = {r.sku: r for r in result.recommendations}
        sku1_rec = by_sku["SKU-001"]
        sku2_rec = by_sku["SKU-002"]
        if sku1_rec.should_reorder_now and sku2_rec.should_reorder_now:
            unconstrained_by_sku = {r.sku: r for r in unconstrained.recommendations}
            frac1 = sku1_rec.recommended_order_quantity / max(unconstrained_by_sku["SKU-001"].recommended_order_quantity, 1)
            frac2 = sku2_rec.recommended_order_quantity / max(unconstrained_by_sku["SKU-002"].recommended_order_quantity, 1)
            assert frac2 >= frac1

    def test_near_zero_budget_resolves_cleanly(self, test_settings, sample_replenishment_request):
        request = sample_replenishment_request.model_copy(update={"budget_constraint": 0.01})
        solver = ReplenishmentSolver(test_settings)
        try:
            result = solver.solve(request)
            assert result.total_order_cost <= 0.02
        except BudgetInfeasibleError:
            pass
