"""Health and readiness routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.dependencies import get_copilot_service
from src.config.settings import Settings, get_settings
from src.services.copilot.copilot_service import CopilotService

router = APIRouter(tags=["health"])


@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict:
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment}


@router.get("/health/ready")
def readiness(copilot: CopilotService = Depends(get_copilot_service)) -> dict:
    """
    The three solvers (replenishment/routing/network) have no external
    dependency and are always "ready" — only the copilot's LLM backend
    can be unreachable, so readiness specifically reports that.
    """
    ollama_ok = copilot.health_check()
    return {"status": "ok" if ollama_ok else "degraded", "ollama_reachable": ollama_ok}
