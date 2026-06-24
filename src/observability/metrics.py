"""Prometheus metrics for SupplyIQ."""
from __future__ import annotations

from prometheus_client import Counter, Histogram

# --------------------------------------------------------------------------
# Solver-level (shared pattern across all three domains)
# --------------------------------------------------------------------------

SOLVE_REQUESTS_TOTAL = Counter(
    "supplyiq_solve_requests_total",
    "Total optimization solve requests",
    labelnames=["domain", "method", "status"],
)

SOLVE_DURATION_SECONDS = Histogram(
    "supplyiq_solve_duration_seconds",
    "Time spent solving an optimization problem",
    labelnames=["domain", "method"],
    buckets=(0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10, 30),
)

HEURISTIC_FALLBACKS_TOTAL = Counter(
    "supplyiq_heuristic_fallbacks_total",
    "Total times the heuristic fallback was used instead of the exact solver",
    labelnames=["domain", "reason"],
)

# --------------------------------------------------------------------------
# Replenishment
# --------------------------------------------------------------------------

REORDER_RECOMMENDATIONS_TOTAL = Counter(
    "supplyiq_reorder_recommendations_total",
    "Total SKU/location reorder recommendations produced",
    labelnames=["should_reorder"],
)

# --------------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------------

UNASSIGNED_STOPS_TOTAL = Counter(
    "supplyiq_unassigned_stops_total",
    "Total delivery stops that could not be assigned to any vehicle",
)

# --------------------------------------------------------------------------
# Network optimization
# --------------------------------------------------------------------------

UNMET_DEMAND_UNITS_TOTAL = Counter(
    "supplyiq_unmet_demand_units_total",
    "Total demand units left unmet across network optimization solves",
)

# --------------------------------------------------------------------------
# Copilot
# --------------------------------------------------------------------------

COPILOT_QUERIES_TOTAL = Counter(
    "supplyiq_copilot_queries_total",
    "Total natural-language copilot queries",
    labelnames=["intent", "status"],
)

COPILOT_LATENCY_SECONDS = Histogram(
    "supplyiq_copilot_latency_seconds",
    "End-to-end copilot query latency",
    buckets=(0.1, 0.5, 1, 2, 5, 10, 20),
)
