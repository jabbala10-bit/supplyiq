# ADR-001: OR-Tools (LP/MIP/CP-SAT) as the Primary Exact Solver Across All Three Domains

## Status
Accepted

## Context
SupplyIQ covers three classically distinct operations-research problems:
inventory replenishment (closed-form inventory theory plus an optional
budget-allocation LP), last-mile vehicle routing (a capacitated VRP with
time windows), and multi-echelon network optimization (a transportation/
facility-flow LP). Each has its own specialized literature and, often,
its own specialized tooling — a real platform team might reach for a
dedicated VRP library for routing and a separate LP solver for network
flow.

## Decision
Use **Google OR-Tools** as the exact-solver backbone for all three
domains: its `linear_solver` (GLOP) module for the replenishment budget
LP and the network transportation LP, and its `constraint_solver`
routing module (CP-SAT-based) for vehicle routing.

Rationale:
- **OR-Tools genuinely covers all three problem shapes well** — this
  isn't a compromise to avoid integrating three different libraries; LP,
  MIP, and capacitated-VRP-with-time-windows are all first-class,
  well-supported problem types in OR-Tools specifically. Real supply-
  chain platforms (including some of the largest logistics and retail
  companies) use exactly this library for exactly these problem classes,
  so this also reflects realistic industry practice, not just
  implementation convenience.
- **One dependency, one mental model for solver status codes, one
  deferred-import pattern** — consistent with this portfolio's existing
  approach (faster-whisper in FieldOpsIQ, confluent-kafka in
  StreamGuardIQ, faiss in RankIQ/RecoIQ): heavy native dependencies are
  imported only inside the method that needs them, so the surrounding
  orchestration logic, domain models, and even the heuristic fallbacks
  can be fully unit-tested without the native package installed.
- Each domain's solver module (`replenishment_solver.py`,
  `vrp_solver.py`, `network_solver.py`) encapsulates its own OR-Tools
  model-building — there's no shared "generic optimization" abstraction
  forcing all three into an artificial common interface, since LP
  variable/constraint construction and CP-SAT routing model construction
  are genuinely different enough that forcing a shared abstraction would
  add indirection without real reuse benefit.

## Consequences
- The replenishment domain's single-SKU math (safety stock, reorder
  point, EOQ) is **not** OR-Tools-driven — it's closed-form inventory
  theory, verified independently against textbook formulas during
  development. OR-Tools only enters the replenishment domain for the
  optional budget-constrained multi-SKU allocation pass, which is a
  genuine LP (continuous knapsack-style resource allocation). This is a
  deliberate scope distinction documented here rather than forcing
  every single-SKU calculation through a "solver" unnecessarily.
- A reviewer questioning "why not a dedicated VRP library (e.g. VROOM)
  or a dedicated LP library (e.g. PuLP, SciPy)" should know the answer
  is consolidation: one dependency, one license, one versioning story,
  covering three problem classes that would otherwise need three
  separate libraries with three separate APIs to learn and maintain.
- This ADR pairs with ADR-002 (the exact/heuristic switchover) — OR-
  Tools' exact solvers are powerful but not unconditionally fast at
  arbitrary scale, so every domain has a documented, sized fallback path
  rather than assuming OR-Tools alone is sufficient for all problem
  sizes.
