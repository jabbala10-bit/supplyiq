"""
Domain schemas for SupplyIQ's natural-language copilot layer.

The copilot never does optimization math itself (ADR-004) — it
translates a natural-language question into either (a) a request to
explain an already-solved plan, or (b) a structured what-if scenario
that triggers a real re-solve via the appropriate exact solver. This
module defines the request/response shapes for that translation layer.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class OptimizationDomain(str, Enum):
    REPLENISHMENT = "replenishment"
    ROUTING = "routing"
    NETWORK = "network"


class CopilotIntent(str, Enum):
    EXPLAIN = "explain"       # "why did you recommend X" — answered from the existing solved result
    WHAT_IF = "what_if"       # "what if warehouse B is closed" — triggers a structured re-solve
    UNKNOWN = "unknown"       # the copilot could not confidently classify the question


class WhatIfModification(BaseModel):
    """
    A single structured change to apply before re-solving. The copilot's
    job is to produce one or more of these from natural language; it
    never edits solver inputs by unstructured free-form text, so every
    modification is auditable and validated against the same Pydantic
    models the original request used (ADR-004).
    """

    target_domain: OptimizationDomain
    field_path: str = Field(description="e.g. 'warehouses[WH-2].is_active'")
    new_value: str = Field(description="String representation of the new value; parsed against the target field's type")
    rationale: str = Field(description="Copilot's own explanation of why it interpreted the question this way")


class CopilotQuery(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    plan_id: str = Field(description="The previously-solved plan this question refers to")
    domain: OptimizationDomain


class CopilotResponse(BaseModel):
    response_id: str = Field(default_factory=_new_id)
    intent: CopilotIntent
    answer_text: str
    modifications_applied: list[WhatIfModification] = Field(default_factory=list)
    new_plan_id: Optional[str] = Field(default=None, description="Set if a what-if re-solve produced a new plan")
    created_at: datetime = Field(default_factory=_utcnow)
