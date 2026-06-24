# ADR-004: The Copilot Never Does Optimization Math — Translation Only

## Status
Accepted

## Context
The natural-language copilot layer is the feature that makes this case
study a "copilot," not just three optimization microservices. The
central design risk: an LLM-based interface to an optimization system
could be built so that the LLM itself estimates costs, infers feasible
allocations, or otherwise produces numeric optimization output directly
— which would mean the system's actual decisions are only as reliable
as the LLM's arithmetic and reasoning, undermining the entire point of
having exact/heuristic solvers in the first place.

## Decision
**The copilot (`CopilotService`) never performs optimization math.**
Every LLM call does exactly one of two things:

1. **EXPLAIN**: answer a question using *only* data already present in
   a previously-solved plan's stored request/result (fetched from
   `SQLiteStorageService` and handed to the LLM as grounding context).
   The LLM's job is natural-language synthesis over real numbers it
   didn't compute.
2. **WHAT_IF**: translate a hypothetical question into one or more
   structured `WhatIfModification` objects (a field path, a new value,
   a rationale) — never a direct answer to "what would happen." Those
   modifications are validated against the real Pydantic request schema
   (`modification_applier.py`) and then handed to the *actual* solver
   for that domain to re-solve genuinely (`CopilotOrchestrator`). The
   LLM proposes a hypothesis; the real solver determines its
   consequences.

The copilot's system prompt explicitly instructs an `UNKNOWN` intent for
anything it can't confidently classify, and the service-layer retry loop
(parse-validate-repair, identical in spirit to RankIQ's and
StreamGuardIQ's structuring-service retry loops) only ever retries
malformed JSON/schema issues — never "the LLM's math looked wrong,"
because the LLM is never asked to produce optimization math to check in
the first place.

Rationale:
- This is the single most important trust property of the whole system.
  An operator asking "what if we close warehouse B" needs the answer to
  reflect a real LP re-solve against real capacity/cost data — not an
  LLM's plausible-sounding guess about what would happen. Separating
  "understand the question" (LLM's job) from "compute the consequence"
  (solver's job) is what makes this safe to trust for actual operational
  decisions.
- `modification_applier.py`'s strict, schema-validated field-path
  application means even a confidently-wrong LLM proposal — e.g. a
  hallucinated field path — fails loudly (`InvalidModificationError`)
  rather than silently corrupting solver input. This was directly
  exercised during development: a real bug in the path-traversal logic
  itself was caught by writing and running a standalone reproduction
  before it ever reached a real test run, underscoring why this
  validation boundary needs to be strict, not permissive.
- Grounding EXPLAIN responses in the actual stored plan data (rather
  than letting the LLM reconstruct numbers from memory of the
  conversation) avoids the model inventing plausible-but-wrong
  explanations — the system prompt explicitly instructs "do not invent
  numbers not present in [the provided plan data]."

## Consequences
- The copilot adds real latency and a real external dependency (Ollama)
  to what would otherwise be a synchronous, dependency-free optimization
  call — by design, this is opt-in (a separate `/copilot/ask` endpoint,
  not something every solve request passes through), so the core
  solving capability of all three domains works identically whether or
  not Ollama is running, mirroring FieldOpsIQ's and StreamGuardIQ's
  pattern of keeping the "always works" core path decoupled from an
  optional enrichment layer.
- A WHAT_IF response always re-solves the *entire* problem from the
  modified request, not an incremental delta — for the problem sizes
  this case study targets, this is fast enough not to matter; at very
  large scale, incremental re-optimization would be a reasonable future
  enhancement, not pursued here to keep the re-solve path simple and
  exactly mirror a fresh `/solve` call.
- Because `field_path` resolution supports both numeric indices and
  human-readable identifiers (`warehouses[WH-2]` or `warehouses[1]`),
  the LLM has flexibility in how it expresses a modification without
  needing to know exact list positions — but this also means the system
  prompt's instruction to "never invent modifications to fields not
  present in the plan's request data" is the only thing preventing the
  LLM from proposing a plausible-looking but nonexistent path; this
  relies on the LLM following instructions, backstopped by
  `InvalidModificationError` catching it when it doesn't.
