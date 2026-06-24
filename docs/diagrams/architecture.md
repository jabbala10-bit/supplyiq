# Architecture Diagrams

## C4 Level 1 - System Context

```mermaid
C4Context
    title SupplyIQ - System Context

    Person(operator, "Supply Chain Operator", "Solves replenishment/routing/network plans, asks the copilot questions")
    System(supplyiq, "SupplyIQ", "Optimization copilot: replenishment, routing, network, plus LLM layer")
    System_Ext(ollama, "Ollama (local)", "Locally-hosted LLM serving the copilot's natural-language layer")

    Rel(operator, supplyiq, "Solves plans, asks explain/what-if questions", "Gradio UI / API")
    Rel(supplyiq, ollama, "Translates NL questions, never does optimization math", "HTTP, localhost")
```

## C4 Level 2 - Containers

```mermaid
C4Container
    title SupplyIQ - Containers

    Person(operator, "Operator")

    Container_Boundary(supplyiq, "SupplyIQ") {
        Container(ui, "Gradio UI", "Python/Gradio", "Tabs per domain + copilot chat")
        Container(api, "FastAPI Service", "Python/FastAPI", "Solve, plan lookup, copilot routes")
        Container(repl, "Replenishment Solver", "Closed-form + OR-Tools LP", "Safety stock, ROP, EOQ, budget allocation")
        Container(route, "Routing Solver", "OR-Tools CP-SAT + greedy fallback", "Capacitated VRP with time windows")
        Container(net, "Network Solver", "OR-Tools LP + greedy fallback", "Transportation/facility-flow optimization")
        Container(copilot, "Copilot Service", "Ollama-backed", "NL translation: explain / what-if classification")
        Container(orch, "Copilot Orchestrator", "Python", "Applies modifications, triggers real re-solves")
        ContainerDb(sqlite, "SQLite (WAL)", "File-based DB", "Solved plans across all 3 domains")
    }

    System_Ext(ollama, "Ollama")

    Rel(operator, ui, "Uses")
    Rel(ui, api, "Calls")
    Rel(api, repl, "Solve requests")
    Rel(api, route, "Solve requests")
    Rel(api, net, "Solve requests")
    Rel(api, orch, "Copilot queries")
    Rel(orch, copilot, "Ask (explain/what-if)")
    Rel(copilot, ollama, "LLM calls")
    Rel(orch, repl, "Re-solve with modifications")
    Rel(orch, route, "Re-solve with modifications")
    Rel(orch, net, "Re-solve with modifications")
    Rel(api, sqlite, "Reads/writes plans")
```

## Exact-vs-Heuristic Decision Flow (shared pattern, ADR-002)

```mermaid
stateDiagram-v2
    [*] --> CheckSize
    CheckSize --> ExactSolve: problem size within budget
    CheckSize --> HeuristicFallback: size exceeds threshold
    ExactSolve --> Solved: optimal/feasible solution found
    ExactSolve --> HeuristicFallback: timeout or infeasible-by-solver-error
    HeuristicFallback --> Solved: greedy solution produced
    Solved --> [*]
```

## Copilot Explain Sequence

```mermaid
sequenceDiagram
    participant Operator
    participant API as FastAPI /copilot/ask
    participant Orch as CopilotOrchestrator
    participant Copilot as CopilotService
    participant DB as SQLite
    participant LLM as Ollama

    Operator->>API: "why does SKU-002 need reordering?"
    API->>Orch: handle_query(query)
    Orch->>Copilot: ask(query)
    Copilot->>DB: load plan request+result data
    Copilot->>LLM: system prompt + plan data + question
    LLM-->>Copilot: intent=explain, answer_text
    Copilot-->>Orch: CopilotResponse(intent=EXPLAIN)
    Orch-->>API: response (no re-solve triggered)
    API-->>Operator: answer_text
```

## Copilot What-If Sequence (real re-solve)

```mermaid
sequenceDiagram
    participant Operator
    participant API as FastAPI /copilot/ask
    participant Orch as CopilotOrchestrator
    participant Copilot as CopilotService
    participant Applier as modification_applier
    participant Solver as Domain Solver
    participant DB as SQLite
    participant LLM as Ollama

    Operator->>API: "what if we close WH-1?"
    API->>Orch: handle_query(query)
    Orch->>Copilot: ask(query)
    Copilot->>DB: load plan data
    Copilot->>LLM: system prompt + plan data + question
    LLM-->>Copilot: intent=what_if, modifications=[...]
    Copilot-->>Orch: CopilotResponse(intent=WHAT_IF)
    Orch->>DB: get original request
    Orch->>Applier: apply_modifications(request, modifications)
    Applier-->>Orch: modified, schema-validated request
    Orch->>Solver: solve(modified_request)
    Solver-->>Orch: new result
    Orch->>DB: save new plan
    Orch-->>API: response + new_plan_id
    API-->>Operator: answer_text + new_plan_id
```

## Domain Model Overview

```mermaid
classDiagram
    class ReplenishmentSolver {
        +solve(request) ReplenishmentPlanResult
        -_recommend_for_sku(sl) ReplenishmentRecommendation
        -_apply_budget_constraint(recs, skus, budget)
    }
    class VehicleRoutingSolver {
        +solve(request) VehicleRoutingResult
        -_solve_exact(request)
        -_solve_heuristic(request, reason)
    }
    class NetworkOptimizationSolver {
        +solve(request) NetworkOptimizationResult
        -_solve_exact(request)
        -_solve_heuristic(request, reason)
    }
    class GreedyNearestNeighborRouter
    class GreedyCostAllocator
    class CopilotOrchestrator {
        +handle_query(query) CopilotResponse
        -_resolve_with_modifications(query, response)
    }
    class CopilotService {
        +ask(query) CopilotResponse
    }

    VehicleRoutingSolver --> GreedyNearestNeighborRouter : falls back to
    NetworkOptimizationSolver --> GreedyCostAllocator : falls back to
    CopilotOrchestrator --> CopilotService : delegates NL understanding
    CopilotOrchestrator --> ReplenishmentSolver : re-solves
    CopilotOrchestrator --> VehicleRoutingSolver : re-solves
    CopilotOrchestrator --> NetworkOptimizationSolver : re-solves
```
