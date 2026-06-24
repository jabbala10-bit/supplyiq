"""
Greedy cost-based allocator — the documented heuristic fallback for
network optimization when the LP exceeds the configured variable-count
budget (ADR-002). For each demand location, greedily ships from the
cheapest available active warehouse with remaining capacity until
demand is met or capacity runs out.

Like the routing domain's heuristic, this is a deliberately simple,
predictable greedy approach rather than a more sophisticated
metaheuristic — see ADR-002.
"""
from __future__ import annotations

from src.domain.network_schemas import (
    NetworkOptimizationRequest,
    NetworkOptimizationResult,
    ShipmentAllocation,
    SolveMethod,
)


class GreedyCostAllocator:
    """Greedily allocates shipments to the cheapest available lane per demand location."""

    def solve(self, request: NetworkOptimizationRequest) -> NetworkOptimizationResult:
        remaining_capacity = {w.warehouse_id: w.capacity_units for w in request.warehouses if w.is_active}
        lanes_by_location: dict[str, list] = {}
        for lane in request.shipping_lanes:
            if lane.warehouse_id in remaining_capacity:
                lanes_by_location.setdefault(lane.location_id, []).append(lane)

        for lanes in lanes_by_location.values():
            lanes.sort(key=lambda l: l.cost_per_unit)

        allocations: list[ShipmentAllocation] = []
        unmet_total = 0

        for loc in request.demand_locations:
            need = loc.demand_units
            for lane in lanes_by_location.get(loc.location_id, []):
                if need <= 0:
                    break
                available = remaining_capacity.get(lane.warehouse_id, 0)
                if lane.max_capacity_units is not None:
                    available = min(available, lane.max_capacity_units)
                ship = min(need, available)
                if ship > 0:
                    allocations.append(
                        ShipmentAllocation(
                            warehouse_id=lane.warehouse_id, location_id=loc.location_id,
                            units_shipped=ship, cost=round(ship * lane.cost_per_unit, 2),
                        )
                    )
                    remaining_capacity[lane.warehouse_id] -= ship
                    need -= ship
            if need > 0:
                unmet_total += need

        total_cost = round(sum(a.cost for a in allocations), 2)
        active_ids = sorted({a.warehouse_id for a in allocations})
        is_feasible = unmet_total == 0 or request.allow_unmet_demand

        return NetworkOptimizationResult(
            allocations=allocations, total_cost=total_cost, unmet_demand_units=unmet_total,
            active_warehouse_ids=active_ids, solve_method=SolveMethod.HEURISTIC, is_feasible=is_feasible,
        )
