"""
Domain-level constants for SupplyIQ.

Centralizing thresholds here keeps the exact-vs-heuristic switchover
(ADR-002) and replenishment safety-stock math (ADR-003) auditable in
one place.
"""
from __future__ import annotations

# --------------------------------------------------------------------------
# Exact-solver size/time budgets — beyond these, fall back to heuristics (ADR-002)
# --------------------------------------------------------------------------

EXACT_SOLVE_TIME_LIMIT_SECONDS: float = 10.0
ROUTING_EXACT_MAX_STOPS: int = 60       # CP-SAT routing solve time grows fast beyond this
NETWORK_EXACT_MAX_VARIABLES: int = 5000  # warehouses x locations LP variable count ceiling
REPLENISHMENT_EXACT_MAX_SKU_LOCATIONS: int = 2000

# --------------------------------------------------------------------------
# Replenishment — safety stock / EOQ (classic inventory theory, see ADR-003)
# --------------------------------------------------------------------------

SERVICE_LEVEL_Z_SCORES: dict[float, float] = {
    0.50: 0.00,
    0.80: 0.84,
    0.90: 1.28,
    0.95: 1.65,
    0.975: 1.96,
    0.99: 2.33,
    0.999: 3.09,
}
DAYS_PER_YEAR: float = 365.0
LOW_STOCK_DAYS_THRESHOLD: float = 3.0  # below this many days of supply, flag as urgent regardless of reorder point math

# --------------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------------

DEFAULT_AVERAGE_SPEED_KMH: float = 40.0
ROUTING_SOLVE_TIME_LIMIT_SECONDS: int = 10

# --------------------------------------------------------------------------
# Network optimization
# --------------------------------------------------------------------------

DEFAULT_UNMET_DEMAND_PENALTY: float = 1_000_000.0

# --------------------------------------------------------------------------
# Copilot
# --------------------------------------------------------------------------

DEFAULT_LLM_MODEL: str = "llama3.1:8b"
DEFAULT_LLM_TEMPERATURE: float = 0.1
COPILOT_MAX_RETRIES: int = 3

# --------------------------------------------------------------------------
# API / rate limiting
# --------------------------------------------------------------------------

DEFAULT_RATE_LIMIT_PER_MINUTE: int = 120

# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------

DEFAULT_SQLITE_PATH: str = "data/supplyiq.db"
