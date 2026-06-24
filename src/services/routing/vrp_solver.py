"""
Vehicle routing solver using OR-Tools' constraint-programming routing
library (`ortools.constraint_solver.routing_enums_pb2` /
`pywrapcp`) — the industry-standard exact/near-exact approach for VRP
with capacity and time-window constraints (ADR-001).

Deferred import of ortools, same pattern as every other heavy native
dependency in this portfolio, so unit tests can exercise the surrounding
orchestration logic without the real solver installed. Routing tests
that need real CP-SAT solving import-skip gracefully if ortools isn't
available (see ADR-002 on the exact/heuristic switchover for the size
threshold that triggers the heuristic path instead).
"""
from __future__ import annotations

import math
import time
from typing import Optional

from src.config.settings import Settings, get_settings
from src.domain.exceptions import InsufficientCapacityError, RoutingError
from src.domain.routing_schemas import (
    DeliveryStop,
    GeoPoint,
    RouteStep,
    SolveMethod,
    Vehicle,
    VehicleRoute,
    VehicleRoutingRequest,
    VehicleRoutingResult,
)
from src.observability.logging import get_logger
from src.observability.metrics import SOLVE_DURATION_SECONDS, SOLVE_REQUESTS_TOTAL, UNASSIGNED_STOPS_TOTAL
from src.services.routing.heuristic_router import GreedyNearestNeighborRouter

logger = get_logger(__name__)


def _haversine_km(a: GeoPoint, b: GeoPoint) -> float:
    """Great-circle distance — used to build the distance matrix every routing approach (exact or heuristic) shares."""
    r = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, [a.latitude, a.longitude, b.latitude, b.longitude])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def build_distance_matrix(depot: GeoPoint, stops: list[DeliveryStop]) -> list[list[float]]:
    """
    Index 0 is always the depot; indices 1..N are stops in the given
    order. Shared by both the exact and heuristic routers so they're
    guaranteed to optimize against identical distances.
    """
    points = [depot] + [s.location for s in stops]
    n = len(points)
    return [[_haversine_km(points[i], points[j]) for j in range(n)] for i in range(n)]


class VehicleRoutingSolver:
    """OR-Tools-backed vehicle routing solver with capacity and time-window constraints."""

    def __init__(self, settings: Optional[Settings] = None):
        self._settings = settings or get_settings()
        self._heuristic = GreedyNearestNeighborRouter()

    def solve(self, request: VehicleRoutingRequest) -> VehicleRoutingResult:
        total_capacity = sum(v.capacity_units for v in request.vehicles)
        total_demand = sum(s.demand_units for s in request.stops)
        if total_demand > total_capacity:
            raise InsufficientCapacityError(
                f"Total demand ({total_demand}) exceeds total vehicle capacity ({total_capacity})."
            )

        if len(request.stops) > self._settings.routing_exact_max_stops:
            return self._solve_heuristic(request, reason="size_exceeded")

        start = time.monotonic()
        try:
            result = self._solve_exact(request)
            elapsed = time.monotonic() - start
            SOLVE_DURATION_SECONDS.labels(domain="routing", method="exact").observe(elapsed)
            SOLVE_REQUESTS_TOTAL.labels(domain="routing", method="exact", status="success").inc()
            result.solve_time_seconds = round(elapsed, 4)
            if result.unassigned_stop_ids:
                UNASSIGNED_STOPS_TOTAL.inc(len(result.unassigned_stop_ids))
            return result
        except RoutingError:
            logger.warning("routing_exact_solve_failed_falling_back_to_heuristic")
            return self._solve_heuristic(request, reason="timeout")

    def _solve_exact(self, request: VehicleRoutingRequest) -> VehicleRoutingResult:
        from ortools.constraint_solver import pywrapcp, routing_enums_pb2

        distance_matrix = build_distance_matrix(request.depot, request.stops)
        n_locations = len(distance_matrix)
        n_vehicles = len(request.vehicles)

        manager = pywrapcp.RoutingIndexManager(n_locations, n_vehicles, 0)
        routing = pywrapcp.RoutingModel(manager)

        speed_km_per_min = request.average_speed_kmh / 60.0

        def distance_callback(from_index, to_index):
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            return int(distance_matrix[from_node][to_node] * 1000)

        transit_callback_index = routing.RegisterTransitCallback(distance_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

        def demand_callback(from_index):
            node = manager.IndexToNode(from_index)
            return 0 if node == 0 else request.stops[node - 1].demand_units

        demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
        routing.AddDimensionWithVehicleCapacity(
            demand_callback_index, 0, [v.capacity_units for v in request.vehicles], True, "Capacity"
        )

        def time_callback(from_index, to_index):
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            travel_min = distance_matrix[from_node][to_node] / speed_km_per_min if speed_km_per_min > 0 else 0
            service_min = 0 if to_node == 0 else request.stops[to_node - 1].service_duration_minutes
            return int(travel_min + service_min)

        time_callback_index = routing.RegisterTransitCallback(time_callback)
        routing.AddDimension(
            time_callback_index, 0, max(v.max_route_duration_minutes for v in request.vehicles), False, "Time"
        )
        time_dimension = routing.GetDimensionOrDie("Time")

        for i, stop in enumerate(request.stops):
            if stop.time_window_start is not None and stop.time_window_end is not None:
                index = manager.NodeToIndex(i + 1)
                start_min = stop.time_window_start.hour * 60 + stop.time_window_start.minute
                end_min = stop.time_window_end.hour * 60 + stop.time_window_end.minute
                time_dimension.CumulVar(index).SetRange(start_min, end_min)

        search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        search_parameters.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        search_parameters.time_limit.FromSeconds(int(self._settings.exact_solve_time_limit_seconds))

        solution = routing.SolveWithParameters(search_parameters)
        if solution is None:
            raise RoutingError("OR-Tools routing solver found no feasible solution within the time budget.")

        return self._extract_solution(request, manager, routing, solution, distance_matrix, speed_km_per_min)

    def _extract_solution(self, request, manager, routing, solution, distance_matrix, speed_km_per_min) -> VehicleRoutingResult:
        routes = []
        assigned_stop_indices: set[int] = set()

        for vehicle_idx, vehicle in enumerate(request.vehicles):
            index = routing.Start(vehicle_idx)
            steps = []
            route_distance = 0.0
            cumulative_load = 0
            cumulative_time = 0.0

            while not routing.IsEnd(index):
                node = manager.IndexToNode(index)
                next_index = solution.Value(routing.NextVar(index))
                next_node = manager.IndexToNode(next_index)

                if node != 0:
                    stop = request.stops[node - 1]
                    cumulative_load += stop.demand_units
                    assigned_stop_indices.add(node - 1)
                    arrival = cumulative_time
                    departure = arrival + stop.service_duration_minutes
                    steps.append(
                        RouteStep(
                            stop_id=stop.stop_id, arrival_time_minutes=arrival,
                            departure_time_minutes=departure, cumulative_load=cumulative_load,
                        )
                    )
                    cumulative_time = departure

                leg_distance = distance_matrix[node][next_node]
                route_distance += leg_distance
                if speed_km_per_min > 0:
                    cumulative_time += leg_distance / speed_km_per_min
                index = next_index

            if steps:
                utilization = (cumulative_load / vehicle.capacity_units * 100) if vehicle.capacity_units > 0 else 0.0
                routes.append(
                    VehicleRoute(
                        vehicle_id=vehicle.vehicle_id, steps=steps, total_distance_km=round(route_distance, 2),
                        total_duration_minutes=round(cumulative_time, 2), load_utilization_pct=round(utilization, 1),
                    )
                )

        unassigned = [request.stops[i].stop_id for i in range(len(request.stops)) if i not in assigned_stop_indices]
        total_distance = sum(r.total_distance_km for r in routes)

        return VehicleRoutingResult(
            routes=routes, unassigned_stop_ids=unassigned, total_distance_km=round(total_distance, 2),
            solve_method=SolveMethod.EXACT,
        )

    def _solve_heuristic(self, request: VehicleRoutingRequest, reason: str) -> VehicleRoutingResult:
        from src.observability.metrics import HEURISTIC_FALLBACKS_TOTAL

        start = time.monotonic()
        HEURISTIC_FALLBACKS_TOTAL.labels(domain="routing", reason=reason).inc()
        result = self._heuristic.solve(request)
        elapsed = time.monotonic() - start
        result.solve_time_seconds = round(elapsed, 4)
        SOLVE_DURATION_SECONDS.labels(domain="routing", method="heuristic").observe(elapsed)
        SOLVE_REQUESTS_TOTAL.labels(domain="routing", method="heuristic", status="success").inc()
        if result.unassigned_stop_ids:
            UNASSIGNED_STOPS_TOTAL.inc(len(result.unassigned_stop_ids))
        return result
