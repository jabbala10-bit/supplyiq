"""
Copilot orchestrator: the glue between CopilotService's natural-
language understanding and the three real solvers. This is the only
place that takes a CopilotResponse with WHAT_IF intent and actually
triggers a re-solve — CopilotService itself never touches a solver
directly (ADR-004).
"""
from __future__ import annotations

from typing import Optional

from src.domain.copilot_schemas import CopilotIntent, CopilotQuery, CopilotResponse, OptimizationDomain
from src.domain.exceptions import CopilotError, PlanNotFoundError
from src.services.copilot.copilot_service import CopilotService
from src.services.copilot.modification_applier import apply_modifications
from src.services.network.network_solver import NetworkOptimizationSolver
from src.services.replenishment.replenishment_solver import ReplenishmentSolver
from src.services.routing.vrp_solver import VehicleRoutingSolver
from src.services.storage.sqlite_service import SQLiteStorageService


class CopilotOrchestrator:
    """Routes copilot WHAT_IF responses through the appropriate solver and persists the new plan."""

    def __init__(
        self,
        copilot: CopilotService,
        replenishment_solver: ReplenishmentSolver,
        routing_solver: VehicleRoutingSolver,
        network_solver: NetworkOptimizationSolver,
        storage: Optional[SQLiteStorageService] = None,
    ):
        self._copilot = copilot
        self._replenishment_solver = replenishment_solver
        self._routing_solver = routing_solver
        self._network_solver = network_solver
        self._storage = storage or SQLiteStorageService()

    def handle_query(self, query: CopilotQuery) -> CopilotResponse:
        """
        Answers the query via CopilotService, and if the resulting
        intent is WHAT_IF, applies the proposed modifications and
        triggers a genuine re-solve, attaching the new plan_id to the
        response so the caller can fetch the updated plan.
        """
        response = self._copilot.ask(query)

        if response.intent != CopilotIntent.WHAT_IF or not response.modifications_applied:
            return response

        new_plan_id = self._resolve_with_modifications(query, response)
        return response.model_copy(update={"new_plan_id": new_plan_id})

    def _resolve_with_modifications(self, query: CopilotQuery, response: CopilotResponse) -> str:
        if query.domain == OptimizationDomain.REPLENISHMENT:
            pair = self._storage.get_replenishment_plan(query.plan_id)
            if pair is None:
                raise PlanNotFoundError(f"No replenishment plan found with id {query.plan_id}")
            original_request, _ = pair
            modified_request = apply_modifications(original_request, response.modifications_applied)
            new_result = self._replenishment_solver.solve(modified_request)
            self._storage.save_replenishment_plan(modified_request, new_result)
            return new_result.plan_id

        if query.domain == OptimizationDomain.ROUTING:
            pair = self._storage.get_routing_plan(query.plan_id)
            if pair is None:
                raise PlanNotFoundError(f"No routing plan found with id {query.plan_id}")
            original_request, _ = pair
            modified_request = apply_modifications(original_request, response.modifications_applied)
            new_result = self._routing_solver.solve(modified_request)
            self._storage.save_routing_plan(modified_request, new_result)
            return new_result.plan_id

        if query.domain == OptimizationDomain.NETWORK:
            pair = self._storage.get_network_plan(query.plan_id)
            if pair is None:
                raise PlanNotFoundError(f"No network plan found with id {query.plan_id}")
            original_request, _ = pair
            modified_request = apply_modifications(original_request, response.modifications_applied)
            new_result = self._network_solver.solve(modified_request)
            self._storage.save_network_plan(modified_request, new_result)
            return new_result.plan_id

        raise CopilotError(f"Unhandled optimization domain: {query.domain}")
