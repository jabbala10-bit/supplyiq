# ADR-002: Sized Heuristic Fallback for Each Domain, Not a Universal Metaheuristic

## Status
Accepted

## Context
Exact OR-Tools solvers (LP, MIP, CP-SAT routing) don't guarantee fast
solve times at arbitrary problem size — a large enough vehicle-routing
instance, or a network with thousands of warehouse-location lane
variables, can exceed any reasonable time budget for an exact solve.
Every domain needs a fallback for "the exact solver would take too
long," and the question is what that fallback should look like.

## Decision
Each domain ships its **own simple, predictable greedy heuristic** as
its fallback, triggered by either (a) problem size exceeding a
configured threshold *before* attempting the exact solve
(`ROUTING_EXACT_MAX_STOPS`, `NETWORK_EXACT_MAX_VARIABLES`,
`REPLENISHMENT_EXACT_MAX_SKU_LOCATIONS`), or (b) the exact solver
actually failing/timing out despite being attempted:

- **Routing**: `GreedyNearestNeighborRouter` — greedily assigns the
  nearest unvisited stop respecting vehicle capacity and time budget.
- **Network**: `GreedyCostAllocator` — for each demand location, ships
  from the cheapest available warehouse with remaining capacity.
- **Replenishment**: no separate heuristic module exists, because the
  per-SKU math (safety stock/ROP/EOQ) is *already* a fast closed-form
  calculation — only the optional budget-allocation LP could need a
  fallback, and that LP is small enough (one variable per reordering
  SKU) that it's not expected to need one in practice at the scales this
  case study targets.

Rationale for **simple greedy heuristics specifically**, rather than a
more sophisticated metaheuristic (simulated annealing, genetic
algorithms, tabu search):
- **Predictability matters more than marginal solution quality for a
  fallback path.** A fallback's job is to produce *some* reasonable
  answer quickly and reliably when the primary path can't — not to
  approach optimality. A greedy heuristic's behavior is easy to reason
  about, easy to unit-test deterministically (no randomness, no tuning
  parameters like cooling schedules or mutation rates), and easy to
  explain to an operator ("we shipped from the cheapest available
  warehouse first") in exactly the way the copilot's explain
  functionality depends on (ADR-004).
- **Both heuristics share their core data-shape logic with the exact
  solver where it matters**: `GreedyNearestNeighborRouter` reuses
  `vrp_solver.build_distance_matrix()` so the exact and heuristic paths
  are guaranteed to optimize against identical distances — this was
  specifically verified during development (the haversine distance
  calculation was checked against a known NYC-to-LA reference distance,
  and the greedy nearest-neighbor selection was verified to visit stops
  in correct distance order).
- A more sophisticated metaheuristic would likely produce better
  solutions on hard instances, but at the cost of needing real tuning
  effort (parameters, convergence criteria) and non-deterministic
  behavior that's harder to test and harder for the copilot to explain
  faithfully. This tradeoff is reasonable for a fallback path; it would
  not be reasonable as the *primary* solving strategy, which is why
  OR-Tools' exact solvers remain the default (ADR-001).

## Consequences
- `SolveMethod.HEURISTIC` is stamped on every result that used the
  fallback path, and `HEURISTIC_FALLBACKS_TOTAL` (labeled by domain and
  reason: `size_exceeded` vs `timeout`) makes fallback frequency an
  observable, alertable metric — a production deployment seeing a high
  heuristic-fallback rate has a clear, actionable signal that its
  exact-solve size/time budgets need revisiting.
- Heuristic solutions are not validated against any optimality gap
  bound — they're "a reasonable answer," not "provably within X% of
  optimal." A deployment that needs a quantified optimality guarantee at
  scale should consider OR-Tools' own large-neighborhood-search/
  metaheuristic options within CP-SAT itself (which can provide an
  anytime, improving-but-bounded-time solution) rather than this
  case study's simple greedy fallback — noted as a reasonable next
  increment, not built here, to keep the fallback's behavior simple and
  predictable per the rationale above.
- The threshold constants themselves
  (`ROUTING_EXACT_MAX_STOPS=60`, `NETWORK_EXACT_MAX_VARIABLES=5000`) are
  reasonable starting points based on general knowledge of where these
  solver classes' practical performance starts to degrade, not values
  empirically tuned against this specific deployment's hardware — a real
  rollout should validate and adjust them against observed solve times.
