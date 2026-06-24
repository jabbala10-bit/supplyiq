"""
Replenishment solver: classic inventory theory (safety stock, reorder
point, economic order quantity) per SKU/location, with an optional
budget-constrained allocation pass across all SKUs using OR-Tools' LP
solver when a total spend cap is provided (ADR-001, ADR-003).

The single-SKU math (safety stock, ROP, EOQ) is closed-form — there's
no "solver" needed for one SKU in isolation, it's textbook formulas.
The actual optimization problem only appears once a *budget constraint*
ties multiple SKUs together: "given $50k to spend this cycle, which
subset of reorders maximizes service-level improvement?" That's where
OR-Tools' linear solver does real work (see `_apply_budget_constraint`).
"""
from __future__ import annotations

import math
import time
from typing import Optional

from src.config.settings import Settings, get_settings
from src.domain.constants import DAYS_PER_YEAR, LOW_STOCK_DAYS_THRESHOLD, SERVICE_LEVEL_Z_SCORES
from src.domain.exceptions import BudgetInfeasibleError, ReplenishmentError
from src.domain.replenishment_schemas import (
    ReplenishmentPlanRequest,
    ReplenishmentPlanResult,
    ReplenishmentRecommendation,
    SKULocation,
    SolveMethod,
)
from src.observability.logging import get_logger
from src.observability.metrics import REORDER_RECOMMENDATIONS_TOTAL, SOLVE_DURATION_SECONDS, SOLVE_REQUESTS_TOTAL

logger = get_logger(__name__)


def _z_score(service_level: float) -> float:
    """Looks up (or interpolates) the z-score for a target service level."""
    if service_level in SERVICE_LEVEL_Z_SCORES:
        return SERVICE_LEVEL_Z_SCORES[service_level]
    levels = sorted(SERVICE_LEVEL_Z_SCORES)
    for lo, hi in zip(levels, levels[1:]):
        if lo <= service_level <= hi:
            frac = (service_level - lo) / (hi - lo)
            return SERVICE_LEVEL_Z_SCORES[lo] + frac * (SERVICE_LEVEL_Z_SCORES[hi] - SERVICE_LEVEL_Z_SCORES[lo])
    return SERVICE_LEVEL_Z_SCORES[levels[-1]]


class ReplenishmentSolver:
    """Computes per-SKU reorder recommendations, with optional budget-constrained allocation."""

    def __init__(self, settings: Optional[Settings] = None):
        self._settings = settings or get_settings()

    def solve(self, request: ReplenishmentPlanRequest) -> ReplenishmentPlanResult:
        start = time.monotonic()
        try:
            recommendations = [self._recommend_for_sku(sl) for sl in request.sku_locations]

            method = SolveMethod.EXACT
            budget_binding = False
            if request.budget_constraint is not None:
                recommendations, budget_binding = self._apply_budget_constraint(
                    recommendations, request.sku_locations, request.budget_constraint
                )

            total_cost = self._total_order_cost(recommendations, request.sku_locations)
            elapsed = time.monotonic() - start

            SOLVE_DURATION_SECONDS.labels(domain="replenishment", method=method.value).observe(elapsed)
            SOLVE_REQUESTS_TOTAL.labels(domain="replenishment", method=method.value, status="success").inc()
            for rec in recommendations:
                REORDER_RECOMMENDATIONS_TOTAL.labels(should_reorder=str(rec.should_reorder_now)).inc()

            return ReplenishmentPlanResult(
                recommendations=recommendations,
                total_order_cost=total_cost,
                budget_constraint_binding=budget_binding,
                solve_method=method,
                solve_time_seconds=round(elapsed, 4),
            )
        except BudgetInfeasibleError:
            raise
        except Exception as exc:  # noqa: BLE001
            SOLVE_REQUESTS_TOTAL.labels(domain="replenishment", method="exact", status="error").inc()
            raise ReplenishmentError(f"Replenishment solve failed: {exc}") from exc

    def _recommend_for_sku(self, sl: SKULocation) -> ReplenishmentRecommendation:
        z = _z_score(sl.service_level_target)
        demand_during_lead_time = sl.daily_demand_forecast * sl.lead_time_days
        safety_stock = z * sl.demand_std_dev * math.sqrt(sl.lead_time_days)
        reorder_point = demand_during_lead_time + safety_stock

        annual_demand = sl.daily_demand_forecast * DAYS_PER_YEAR
        annual_holding_cost_per_unit = sl.unit_cost * sl.holding_cost_rate
        if annual_holding_cost_per_unit > 0 and sl.order_cost > 0:
            eoq = math.sqrt((2 * annual_demand * sl.order_cost) / annual_holding_cost_per_unit)
        else:
            eoq = demand_during_lead_time

        if sl.max_capacity is not None:
            eoq = min(eoq, max(0.0, sl.max_capacity - sl.current_stock))

        days_of_supply = sl.current_stock / sl.daily_demand_forecast if sl.daily_demand_forecast > 0 else float("inf")
        should_reorder = sl.current_stock <= reorder_point

        reasoning = []
        if should_reorder:
            reasoning.append(
                f"Current stock ({sl.current_stock}) is at or below the reorder point ({reorder_point:.0f})."
            )
        if days_of_supply < LOW_STOCK_DAYS_THRESHOLD:
            reasoning.append(
                f"Only {days_of_supply:.1f} days of supply remain — below the {LOW_STOCK_DAYS_THRESHOLD:.0f}-day urgency threshold."
            )
        if not reasoning:
            reasoning.append(
                f"Current stock ({sl.current_stock}) exceeds the reorder point ({reorder_point:.0f}); no action needed."
            )

        return ReplenishmentRecommendation(
            sku=sl.sku,
            location_id=sl.location_id,
            reorder_point=round(reorder_point, 2),
            safety_stock=round(safety_stock, 2),
            economic_order_quantity=round(eoq, 2),
            recommended_order_quantity=round(eoq) if should_reorder else 0,
            should_reorder_now=should_reorder,
            days_of_supply_remaining=round(days_of_supply, 2) if days_of_supply != float("inf") else 9999.0,
            solve_method=SolveMethod.EXACT,
            reasoning=reasoning,
        )

    def _apply_budget_constraint(
        self,
        recommendations: list[ReplenishmentRecommendation],
        sku_locations: list[SKULocation],
        budget: float,
    ) -> tuple[list[ReplenishmentRecommendation], bool]:
        """
        When a total spend cap is provided, this is a genuine knapsack-
        style LP: which subset (and what fraction of each EOQ) of the
        recommended reorders should actually be placed this cycle to
        maximize total urgency-weighted benefit within budget? Solved
        via OR-Tools' continuous linear solver (GLOP) — a continuous
        relaxation rather than a 0/1 MIP, since partial reorders are
        operationally normal in replenishment (ADR-001).
        """
        from ortools.linear_solver import pywraplp

        cost_by_sku = {sl.sku: sl.unit_cost for sl in sku_locations}
        total_unconstrained_cost = sum(
            rec.recommended_order_quantity * cost_by_sku[rec.sku] for rec in recommendations if rec.should_reorder_now
        )
        if total_unconstrained_cost <= budget:
            return recommendations, False

        solver = pywraplp.Solver.CreateSolver("GLOP")
        if solver is None:
            raise ReplenishmentError("Could not create OR-Tools LP solver (GLOP backend unavailable).")

        fractions = {}
        urgency_weight = {}
        for rec in recommendations:
            if not rec.should_reorder_now:
                continue
            fractions[rec.sku] = solver.NumVar(0.0, 1.0, f"frac_{rec.sku}")
            urgency_weight[rec.sku] = 1.0 / max(rec.days_of_supply_remaining, 0.1)

        if not fractions:
            return recommendations, False

        budget_constraint = solver.Constraint(0, budget, "budget")
        for rec in recommendations:
            if rec.sku in fractions:
                budget_constraint.SetCoefficient(
                    fractions[rec.sku], rec.recommended_order_quantity * cost_by_sku[rec.sku]
                )

        objective = solver.Objective()
        for sku, var in fractions.items():
            objective.SetCoefficient(var, urgency_weight[sku])
        objective.SetMaximization()

        status = solver.Solve()
        if status != pywraplp.Solver.OPTIMAL:
            raise BudgetInfeasibleError(
                f"Budget allocation LP did not reach optimality (status={status}); "
                f"budget {budget} may be too small relative to required reorders."
            )

        adjusted = []
        for rec in recommendations:
            if rec.sku in fractions:
                fraction = fractions[rec.sku].solution_value()
                new_qty = round(rec.recommended_order_quantity * fraction)
                adjusted.append(
                    rec.model_copy(
                        update={
                            "recommended_order_quantity": new_qty,
                            "reasoning": rec.reasoning
                            + [f"Budget-constrained: funded {fraction * 100:.0f}% of full recommended quantity."],
                        }
                    )
                )
            else:
                adjusted.append(rec)
        return adjusted, True

    @staticmethod
    def _total_order_cost(recommendations: list[ReplenishmentRecommendation], sku_locations: list[SKULocation]) -> float:
        cost_by_sku = {sl.sku: sl.unit_cost for sl in sku_locations}
        return round(sum(rec.recommended_order_quantity * cost_by_sku[rec.sku] for rec in recommendations), 2)
