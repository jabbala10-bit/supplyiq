# SupplyIQ

**CS-10 — Supply Chain Optimization Copilot (Replenishment + Routing + Network), with an LLM Layer**

Three classic operations-research problems — when to reorder inventory,
how to route last-mile deliveries, and how to allocate shipments across
a warehouse network — solved with OR-Tools (LP/MIP/CP-SAT), with a
documented heuristic fallback for problems too large to solve exactly in
budget, and a natural-language copilot layer that explains decisions and
runs real what-if re-solves, never doing optimization math itself.

```
Replenishment: closed-form inventory theory + OR-Tools LP (budget allocation)
Routing:       OR-Tools CP-SAT VRP + greedy nearest-neighbor fallback
Network:       OR-Tools transportation LP + greedy cost-based fallback
                              |
                    Copilot (Ollama-backed)
            "why?" -> grounded explanation from solved plan data
        "what if?" -> structured modification -> REAL re-solve -> new plan
```

## Why this case study

This is the tenth and final entry in a Forward-Deployed-Engineer-style
portfolio spanning manufacturing QA, defect detection, adaptive RAG
support, biomedical fine-tuning, multi-GPU inference, offline edge
pipelines, real-time fraud detection, semantic search, and
personalization. As the capstone, it deliberately combines two threads
from earlier entries: classic operations-research solving (a domain none
of the other nine touch) and an LLM layer with a hard trust boundary
(echoing RankIQ's and StreamGuardIQ's structured-output retry patterns,
but applied here to a fundamentally higher-stakes question: can an LLM
be trusted near a system that makes real operational decisions, and if
so, exactly how much of the decision should it be allowed to touch).

## Architecture

See [`docs/diagrams/architecture.md`](docs/diagrams/architecture.md) for
C4 diagrams, the exact-vs-heuristic decision flow, and both copilot
sequence diagrams (explain vs. what-if).

```
src/
├── domain/          # Schemas split by domain: replenishment, routing, network, copilot
├── config/          # 12-factor Settings — solver size/time budgets, LLM config
├── services/
│   ├── replenishment/  # Closed-form safety stock/ROP/EOQ + OR-Tools budget LP (ADR-001, ADR-003)
│   ├── routing/          # OR-Tools CP-SAT VRP + greedy heuristic fallback (ADR-002)
│   ├── network/            # OR-Tools transportation LP + greedy heuristic fallback (ADR-002)
│   ├── copilot/               # NL translation only — never solves (ADR-004)
│   └── storage/                  # SQLite — solved plans across all 3 domains
├── api/             # FastAPI routes per domain + copilot
└── ui/              # Gradio — one tab per domain + a copilot chat tab
```

ADRs covering every consequential decision:

| ADR | Decision |
|---|---|
| [001](docs/adr/ADR-001-ortools-across-domains.md) | OR-Tools as the primary exact solver across all three domains |
| [002](docs/adr/ADR-002-sized-heuristic-fallback.md) | Sized, simple greedy heuristic fallback per domain, not a universal metaheuristic |
| [003](docs/adr/ADR-003-closed-form-inventory-theory.md) | Closed-form inventory theory, not a forecasting model |
| [004](docs/adr/ADR-004-copilot-translation-only.md) | The copilot never does optimization math — translation only |

## Quickstart

```bash
make dev              # installs deps, creates .env and data dir
make run-api            # starts FastAPI on :8000 - all 3 solver domains work immediately
make run-ui                # starts the demo UI on :7860
```

The copilot needs Ollama:

```bash
make docker-up                                              # starts Ollama
docker compose -f deployment/docker/docker-compose.yml \
  exec ollama ollama pull llama3.1:8b
```

Try it: solve a plan in any UI tab, copy its auto-filled Plan ID into the
Copilot tab, and ask "why does SKU-002 need reordering?" or "what if we
close WH-1?"

## Testing

```bash
make test              # full suite: unit + integration + e2e
make test-unit         # fast - ortools-dependent tests import-skip gracefully if not installed
make test-integration  # real SQLite + real heuristic solvers + mocked LLM
make test-e2e          # full solve -> explain -> what-if -> re-solve journey through the API
```

The exact OR-Tools solvers are deferred-imported (same pattern as every
other native dependency in this portfolio); the greedy heuristic
fallbacks are pure Python and fully exercised in unit tests without
`ortools` installed at all.

## API surface

| Route | Purpose |
|---|---|
| `POST /replenishment/solve`, `GET /replenishment/plans/{id}` | Reorder recommendations, optional budget allocation |
| `POST /routing/solve`, `GET /routing/plans/{id}` | Capacitated VRP with time windows |
| `POST /network/solve`, `GET /network/plans/{id}` | Warehouse-to-location shipment allocation |
| `POST /copilot/ask` | Natural-language explain/what-if over any solved plan |
| `GET /health`, `GET /health/ready` | Liveness / readiness (readiness reports Ollama reachability) |
| `GET /metrics` | Prometheus metrics |

## Observability

Structured JSON logs and Prometheus metrics covering solve duration and
status by domain/method, heuristic-fallback rate by reason, reorder/
unassigned-stop/unmet-demand counts, and copilot query latency/intent
distribution — see [`src/observability/metrics.py`](src/observability/metrics.py).

## Known limitations / honest caveats

- This was built in a sandboxed environment with no `pydantic`/`fastapi`/
  `ortools`/`pytest` and no network access, so the full suite could not
  be executed end-to-end here. To compensate, every piece of pure-Python
  logic was independently verified with standalone scripts during
  development: the safety-stock/reorder-point/EOQ formulas were checked
  against manual textbook calculations (exact match); the haversine
  distance and greedy nearest-neighbor routing logic were checked
  against a known reference distance and verified visit-order; the
  greedy cost allocator was checked to prefer cheaper lanes correctly;
  and — critically — a **real bug** in the copilot's dotted-path
  modification-applier was found and fixed via direct execution before
  ever reaching the test suite (a `warehouses[WH-2].is_active`-style path
  was resolving incorrectly), then re-verified correct after the fix.
  The full what-if network re-solve scenario (closing a warehouse
  producing exactly the expected unmet-demand shortfall) was also
  verified standalone. Every file is `py_compile`/`ast.parse`-clean
  (59/59). Run `make test` yourself in a networked environment for full
  pass/fail confirmation of the OR-Tools-dependent exact-solver paths
  specifically, which could not be executed at all here.
- No demand-forecasting model is included (ADR-003) - the replenishment
  domain consumes a forecast as input, by design.
- The copilot's what-if re-solve always re-solves the full problem from
  scratch rather than incrementally (ADR-004) - fine at this case
  study's scale, a reasonable future optimization at larger scale.
