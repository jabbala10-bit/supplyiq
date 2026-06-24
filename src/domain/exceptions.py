"""Typed domain exceptions for SupplyIQ."""


class SupplyIQError(Exception):
    """Base class for all domain-level errors."""


# --------------------------------------------------------------------------
# Solver-layer (shared across replenishment, routing, network)
# --------------------------------------------------------------------------

class SolverError(SupplyIQError):
    """Base class for optimization solver failures."""


class InfeasibleProblemError(SolverError):
    """Raised when the exact solver proves no feasible solution exists."""


class SolverTimeoutError(SolverError):
    """Raised when the exact solver exceeds its time budget without a feasible solution."""


class HeuristicFallbackError(SolverError):
    """Raised when even the heuristic fallback fails to produce a usable solution."""


# --------------------------------------------------------------------------
# Replenishment
# --------------------------------------------------------------------------

class ReplenishmentError(SupplyIQError):
    """Raised on replenishment-planning failures."""


class BudgetInfeasibleError(ReplenishmentError):
    """Raised when a budget constraint makes even minimal reordering infeasible."""


# --------------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------------

class RoutingError(SupplyIQError):
    """Raised on vehicle-routing failures."""


class InsufficientCapacityError(RoutingError):
    """Raised when total vehicle capacity cannot possibly cover total demand."""


# --------------------------------------------------------------------------
# Network optimization
# --------------------------------------------------------------------------

class NetworkOptimizationError(SupplyIQError):
    """Raised on network/facility-flow optimization failures."""


# --------------------------------------------------------------------------
# Copilot
# --------------------------------------------------------------------------

class CopilotError(SupplyIQError):
    """Base class for copilot layer failures."""


class LLMUnavailableError(CopilotError):
    """Raised when the configured LLM endpoint is unreachable."""


class IntentClassificationError(CopilotError):
    """Raised when the copilot cannot confidently classify a question's intent."""


class InvalidModificationError(CopilotError):
    """Raised when a proposed what-if modification doesn't validate against the target schema."""


class PlanNotFoundError(CopilotError):
    """Raised when a copilot query references a plan_id that doesn't exist."""


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------

class StorageError(SupplyIQError):
    """Raised on persistence read/write failures."""


# --------------------------------------------------------------------------
# Config / auth
# --------------------------------------------------------------------------

class ConfigurationError(SupplyIQError):
    """Raised when required configuration/secrets are missing at startup."""


class AuthenticationError(SupplyIQError):
    """Raised when an API request fails authentication."""


class RateLimitExceededError(SupplyIQError):
    """Raised when a client exceeds the configured rate limit."""
