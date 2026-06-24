"""
Greedy nearest-neighbor heuristic router — the documented fallback used
when problem size exceeds the exact solver's practical budget
(`ROUTING_EXACT_MAX_STOPS`) or when the exact solver times out without
a feasible solution (ADR-002).

This is intentionally a simple, well-understood heuristic (greedy
nearest-unvisited-stop, respecting capacity) rather than a more
sophisticated metaheuristic (simulated annealing, genetic algorithms) —
see ADR-002 for why "simple and predictable" beats "fancier but harder
to reason about" for a fallback path specifically.
"""
from __future__ import annotations

from src.domain.routing_schemas import (
    RouteStep,
    SolveMethod,
    VehicleRoute,
    VehicleRoutingRequest,
    VehicleRoutingResult,
)


class GreedyNearestNeighborRouter:
    """Assigns stops to vehicles greedily by nearest-unvisited-stop, respecting capacity."""

    def solve(self, request: VehicleRoutingRequest) -> VehicleRoutingResult:
        from src.services.routing.vrp_solver import build_distance_matrix

        distance_matrix = build_distance_matrix(request.depot, request.stops)
        speed_km_per_min = request.average_speed_kmh / 60.0

        remaining = list(range(len(request.stops)))
        routes: list[VehicleRoute] = []

        for vehicle in request.vehicles:
            if not remaining:
                break
            steps: list[RouteStep] = []
            current_node = 0
            load = 0
            cumulative_time = 0.0
            route_distance = 0.0

            while True:
                candidates = [
                    i for i in remaining
                    if load + request.stops[i].demand_units <= vehicle.capacity_units
                ]
                if not candidates:
                    break

                next_idx = min(candidates, key=lambda i: distance_matrix[current_node][i + 1])
                stop = request.stops[next_idx]
                leg_distance = distance_matrix[current_node][next_idx + 1]

                travel_min = leg_distance / speed_km_per_min if speed_km_per_min > 0 else 0
                projected_time = cumulative_time + travel_min + stop.service_duration_minutes
                if projected_time > vehicle.max_route_duration_minutes:
                    break

                load += stop.demand_units
                route_distance += leg_distance
                cumulative_time += travel_min
                arrival = cumulative_time
                cumulative_time += stop.service_duration_minutes
                departure = cumulative_time

                steps.append(
                    RouteStep(
                        stop_id=stop.stop_id, arrival_time_minutes=arrival,
                        departure_time_minutes=departure, cumulative_load=load,
                    )
                )
                current_node = next_idx + 1
                remaining.remove(next_idx)

            if steps:
                utilization = (load / vehicle.capacity_units * 100) if vehicle.capacity_units > 0 else 0.0
                routes.append(
                    VehicleRoute(
                        vehicle_id=vehicle.vehicle_id, steps=steps, total_distance_km=round(route_distance, 2),
                        total_duration_minutes=round(cumulative_time, 2), load_utilization_pct=round(utilization, 1),
                    )
                )

        unassigned_ids = [request.stops[i].stop_id for i in remaining]
        total_distance = sum(r.total_distance_km for r in routes)

        return VehicleRoutingResult(
            routes=routes, unassigned_stop_ids=unassigned_ids, total_distance_km=round(total_distance, 2),
            solve_method=SolveMethod.HEURISTIC,
        )
