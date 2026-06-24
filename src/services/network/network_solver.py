"""
Network optimization solver: the classic transportation-problem LP —
minimize total shipping cost from warehouses to demand locations,
subject to warehouse capacity and demand satisfaction (ADR-001). Solved
via OR-Tools' linear solver (GLOP); falls back to a greedy cost-based
heuristic for problems exceeding the configured variable-count budget
(ADR-002).
"""
from __future__ import annotations

import time
from typing import Optional

from src.config.settings import Settings, get_settings
from src.domain.exceptions import InfeasibleProblemError, NetworkOptimizationError
from src.domain.network_schemas import (
    NetworkOptimizationRequest,
    NetworkOptimizationResult,
    ShipmentAllocation,
    SolveMethod,
)
from src.observability.logging import get_logger
from src.observability.metrics import (
    HEURISTIC_FALLBACKS_TOTAL,
    SOLVE_DURATION_SECONDS,
    SOLVE_REQUESTS_TOTAL,
    UNMET_DEMAND_UNITS_TOTAL,
)
from src.services.network.greedy_allocator import GreedyCostAllocator

logger = get_logger(__name__)


class NetworkOptimizationSolver:
    """OR-Tools LP-backed transportation/facility-flow solver."""

    def __init__(self, settings: Optional[Settings] = None):
        self._settings = settings or get_settings()
        self._heuristic = GreedyCostAllocator()

    def solve(self, request: NetworkOptimizationRequest) -> NetworkOptimizationResult:
        n_variables = len(request.shipping_lanes)
        if n_variables > self._settings.network_exact_max_variables:
            return self._solve_heuristic(request, reason="size_exceeded")

        start = time.monotonic()
        try:
            result = self._solve_exact(request)
            elapsed = time.monotonic() - start
            result.solve_time_seconds = round(elapsed, 4)
            SOLVE_DURATION_SECONDS.labels(domain="network", method="exact").observe(elapsed)
            SOLVE_REQUESTS_TOTAL.labels(domain="network", method="exact", status="success").inc()
            if result.unmet_demand_units > 0:
                UNMET_DEMAND_UNITS_TOTAL.inc(result.unmet_demand_units)
            return result
        except InfeasibleProblemError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("network_exact_solve_failed_falling_back_to_heuristic", error=str(exc))
            return self._solve_heuristic(request, reason="timeout")

    def _solve_exact(self, request: NetworkOptimizationRequest) -> NetworkOptimizationResult:
        from ortools.linear_solver import pywraplp

        solver = pywraplp.Solver.CreateSolver("GLOP")
        if solver is None:
            raise NetworkOptimizationError("Could not create OR-Tools LP solver (GLOP backend unavailable).")

        active_warehouses = {w.warehouse_id: w for w in request.warehouses if w.is_active}
        demand_by_location = {d.location_id: d.demand_units for d in request.demand_locations}

        lane_vars = {}
        for lane in request.shipping_lanes:
            if lane.warehouse_id not in active_warehouses:
                continue
            upper_bound = lane.max_capacity_units if lane.max_capacity_units is not None else solver.infinity()
            lane_vars[(lane.warehouse_id, lane.location_id)] = solver.NumVar(
                0, upper_bound, f"x_{lane.warehouse_id}_{lane.location_id}"
            )

        if not lane_vars:
            raise InfeasibleProblemError("No active warehouse has a shipping lane to any demand location.")

        unmet_vars = {}
        if request.allow_unmet_demand:
            for loc in request.demand_locations:
                unmet_vars[loc.location_id] = solver.NumVar(0, loc.demand_units, f"unmet_{loc.location_id}")

        for loc in request.demand_locations:
            lanes_to_loc = [v for (wh, lo), v in lane_vars.items() if lo == loc.location_id]
            if not lanes_to_loc and not request.allow_unmet_demand:
                raise InfeasibleProblemError(
                    f"Demand location {loc.location_id} has no shipping lane and unmet demand is not allowed."
                )
            constraint_expr = sum(lanes_to_loc) if lanes_to_loc else 0
            if request.allow_unmet_demand:
                constraint_expr = constraint_expr + unmet_vars[loc.location_id]
            solver.Add(constraint_expr == demand_by_location[loc.location_id])

        for wh_id, warehouse in active_warehouses.items():
            lanes_from_wh = [v for (wh, lo), v in lane_vars.items() if wh == wh_id]
            if lanes_from_wh:
                solver.Add(sum(lanes_from_wh) <= warehouse.capacity_units)

        cost_by_lane = {(l.warehouse_id, l.location_id): l.cost_per_unit for l in request.shipping_lanes}
        objective_terms = [cost_by_lane[key] * var for key, var in lane_vars.items()]
        if request.allow_unmet_demand:
            objective_terms += [request.unmet_demand_penalty_per_unit * v for v in unmet_vars.values()]
        solver.Minimize(sum(objective_terms))

        status = solver.Solve()
        if status == pywraplp.Solver.INFEASIBLE:
            raise InfeasibleProblemError(
                "Network optimization problem is infeasible — demand cannot be met given warehouse "
                "capacity and lane availability. Consider allow_unmet_demand=true or adding capacity."
            )
        if status != pywraplp.Solver.OPTIMAL:
            raise NetworkOptimizationError(f"LP solver did not reach optimality (status={status}).")

        allocations = []
        for (wh_id, loc_id), var in lane_vars.items():
            units = round(var.solution_value())
            if units > 0:
                allocations.append(
                    ShipmentAllocation(
                        warehouse_id=wh_id, location_id=loc_id, units_shipped=units,
                        cost=round(units * cost_by_lane[(wh_id, loc_id)], 2),
                    )
                )

        total_cost = round(sum(a.cost for a in allocations), 2)
        unmet_total = round(sum(v.solution_value() for v in unmet_vars.values())) if unmet_vars else 0
        active_ids = sorted({a.warehouse_id for a in allocations})

        return NetworkOptimizationResult(
            allocations=allocations, total_cost=total_cost, unmet_demand_units=unmet_total,
            active_warehouse_ids=active_ids, solve_method=SolveMethod.EXACT, is_feasible=True,
        )

    def _solve_heuristic(self, request: NetworkOptimizationRequest, reason: str) -> NetworkOptimizationResult:
        start = time.monotonic()
        HEURISTIC_FALLBACKS_TOTAL.labels(domain="network", reason=reason).inc()
        result = self._heuristic.solve(request)
        elapsed = time.monotonic() - start
        result.solve_time_seconds = round(elapsed, 4)
        SOLVE_DURATION_SECONDS.labels(domain="network", method="heuristic").observe(elapsed)
        SOLVE_REQUESTS_TOTAL.labels(domain="network", method="heuristic", status="success").inc()
        if result.unmet_demand_units > 0:
            UNMET_DEMAND_UNITS_TOTAL.inc(result.unmet_demand_units)
        return result
