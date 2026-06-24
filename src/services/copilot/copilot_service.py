"""
Copilot service: the natural-language layer over the three optimization
domains (ADR-004).

Critically, the copilot NEVER does optimization math itself — every
LLM call either (a) explains an already-solved plan using only data
pulled from that plan's stored result, or (b) proposes structured
WhatIfModification objects which are validated against the real domain
schemas and then trigger a genuine re-solve through the appropriate
exact/heuristic solver. The LLM's role is strictly translation: natural
language in, either an explanation grounded in real solved data, or a
structured, schema-validated modification request, out.
"""
from __future__ import annotations

import json
import time
from typing import Optional

import httpx

from src.config.settings import Settings, get_settings
from src.domain.constants import COPILOT_MAX_RETRIES
from src.domain.copilot_schemas import (
    CopilotIntent,
    CopilotQuery,
    CopilotResponse,
    OptimizationDomain,
    WhatIfModification,
)
from src.domain.exceptions import (
    IntentClassificationError,
    InvalidModificationError,
    LLMUnavailableError,
    PlanNotFoundError,
)
from src.observability.logging import get_logger
from src.observability.metrics import COPILOT_LATENCY_SECONDS, COPILOT_QUERIES_TOTAL
from src.services.storage.sqlite_service import SQLiteStorageService

logger = get_logger(__name__)

_SYSTEM_PROMPT = """You are a supply-chain optimization copilot. You help operators
understand and adjust optimization plans for inventory replenishment, vehicle routing,
and warehouse network allocation.

You will be given a solved plan's data and a question about it. Respond with ONLY a JSON
object, no markdown fences, no commentary, matching this schema:
{
  "intent": one of ["explain", "what_if", "unknown"],
  "answer_text": "your natural-language answer or explanation, 1-4 sentences",
  "modifications": [
    {
      "field_path": "e.g. 'warehouses[WH-2].is_active'",
      "new_value": "string representation of the new value, e.g. 'false'",
      "rationale": "why you interpreted the question this way"
    }
  ]
}

Rules:
- Use "explain" when the question asks why a decision was made — answer using only the
  provided plan data, do not invent numbers not present in it.
- Use "what_if" when the question proposes a hypothetical change (closing a warehouse,
  changing a budget, adding a vehicle) — populate "modifications" with the structured
  change(s) needed; leave answer_text as a brief restatement of what you're testing.
- Use "unknown" if the question is unrelated to the plan or you cannot confidently
  classify it — do not guess.
- Never invent modifications to fields not present in the plan's request data.
"""


class CopilotService:
    """Translates natural-language questions into explanations or structured what-if re-solves."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        client: Optional[httpx.Client] = None,
        storage: Optional[SQLiteStorageService] = None,
    ):
        self._settings = settings or get_settings()
        self._client = client or httpx.Client(base_url=self._settings.ollama_base_url, timeout=60)
        self._storage = storage or SQLiteStorageService(self._settings)

    def health_check(self) -> bool:
        try:
            resp = self._client.get("/api/tags")
            return resp.status_code == 200
        except httpx.RequestError:
            return False

    def ask(self, query: CopilotQuery) -> CopilotResponse:
        """
        Answers a natural-language question about a previously-solved
        plan. Returns either an EXPLAIN response (grounded in the
        existing plan data) or a WHAT_IF response (with structured
        modifications the caller's orchestration layer uses to trigger
        a real re-solve).

        Raises:
            PlanNotFoundError: the referenced plan_id doesn't exist.
            LLMUnavailableError: Ollama unreachable.
            IntentClassificationError: the LLM's output never validated after retries.
        """
        start = time.monotonic()
        plan_data = self._load_plan_data(query.plan_id, query.domain)
        if plan_data is None:
            raise PlanNotFoundError(f"No {query.domain.value} plan found with id {query.plan_id}")

        last_error: Optional[str] = None
        for attempt in range(1, COPILOT_MAX_RETRIES + 1):
            try:
                raw = self._call_llm(query.question, plan_data, repair_hint=last_error)
                response = self._parse_response(raw, query.domain)

                elapsed = time.monotonic() - start
                COPILOT_LATENCY_SECONDS.observe(elapsed)
                COPILOT_QUERIES_TOTAL.labels(intent=response.intent.value, status="success").inc()
                logger.info("copilot_query_answered", intent=response.intent.value, attempt=attempt)
                return response

            except httpx.RequestError as exc:
                COPILOT_QUERIES_TOTAL.labels(intent="unknown", status="unavailable").inc()
                raise LLMUnavailableError(
                    f"Could not reach Ollama at {self._settings.ollama_base_url}: {exc}"
                ) from exc

            except (json.JSONDecodeError, ValueError, InvalidModificationError) as exc:
                last_error = str(exc)
                logger.warning("copilot_response_retry", attempt=attempt, error=last_error)
                continue

        COPILOT_QUERIES_TOTAL.labels(intent="unknown", status="error").inc()
        raise IntentClassificationError(
            f"Copilot could not produce a valid response after {COPILOT_MAX_RETRIES} attempts. Last error: {last_error}"
        )

    def _load_plan_data(self, plan_id: str, domain: OptimizationDomain) -> Optional[dict]:
        if domain == OptimizationDomain.REPLENISHMENT:
            pair = self._storage.get_replenishment_plan(plan_id)
        elif domain == OptimizationDomain.ROUTING:
            pair = self._storage.get_routing_plan(plan_id)
        else:
            pair = self._storage.get_network_plan(plan_id)

        if pair is None:
            return None
        request, result = pair
        return {"request": request.model_dump(mode="json"), "result": result.model_dump(mode="json")}

    def _call_llm(self, question: str, plan_data: dict, repair_hint: Optional[str]) -> dict:
        user_prompt = f"Plan data:\n{json.dumps(plan_data, default=str)}\n\nQuestion: {question}"
        if repair_hint:
            user_prompt += (
                f"\n\nYour previous response was invalid: '{repair_hint}'. Produce a corrected JSON object only."
            )

        resp = self._client.post(
            "/api/generate",
            json={
                "model": self._settings.llm_model,
                "system": _SYSTEM_PROMPT,
                "prompt": user_prompt,
                "format": "json",
                "stream": False,
                "options": {"temperature": self._settings.llm_temperature},
            },
        )
        resp.raise_for_status()
        body = resp.json()
        return json.loads(body.get("response", ""))

    def _parse_response(self, raw: dict, domain: OptimizationDomain) -> CopilotResponse:
        try:
            intent = CopilotIntent(raw["intent"])
            answer_text = raw["answer_text"]
            modifications_raw = raw.get("modifications", [])

            modifications = [
                WhatIfModification(
                    target_domain=domain,
                    field_path=m["field_path"],
                    new_value=str(m["new_value"]),
                    rationale=m.get("rationale", ""),
                )
                for m in modifications_raw
            ]
        except (KeyError, ValueError) as exc:
            raise InvalidModificationError(f"Schema validation failed: {exc}") from exc

        return CopilotResponse(intent=intent, answer_text=answer_text, modifications_applied=modifications)

    def close(self) -> None:
        self._client.close()
