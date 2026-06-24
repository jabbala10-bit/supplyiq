"""
SQLite storage service: persists solved plans across all three
optimization domains plus copilot interaction history, keyed by
plan_id so the copilot layer can look up "the plan this question refers
to" regardless of which domain it came from.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from src.config.settings import Settings, get_settings
from src.domain.exceptions import StorageError
from src.domain.network_schemas import NetworkOptimizationRequest, NetworkOptimizationResult
from src.domain.replenishment_schemas import ReplenishmentPlanRequest, ReplenishmentPlanResult
from src.domain.routing_schemas import VehicleRoutingRequest, VehicleRoutingResult
from src.observability.logging import get_logger

logger = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
    plan_id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    request_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_plans_domain ON plans (domain);
"""


class SQLiteStorageService:
    """Connection-per-call SQLite storage with WAL mode."""

    def __init__(self, settings: Optional[Settings] = None):
        self._settings = settings or get_settings()
        self._db_path = self._settings.sqlite_path
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def save_replenishment_plan(self, request: ReplenishmentPlanRequest, result: ReplenishmentPlanResult) -> None:
        self._save_plan(result.plan_id, "replenishment", request, result)

    def save_routing_plan(self, request: VehicleRoutingRequest, result: VehicleRoutingResult) -> None:
        self._save_plan(result.plan_id, "routing", request, result)

    def save_network_plan(self, request: NetworkOptimizationRequest, result: NetworkOptimizationResult) -> None:
        self._save_plan(result.plan_id, "network", request, result)

    def _save_plan(self, plan_id: str, domain: str, request, result) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO plans (plan_id, domain, request_json, result_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(plan_id) DO UPDATE SET
                        request_json=excluded.request_json, result_json=excluded.result_json
                    """,
                    (plan_id, domain, request.model_dump_json(), result.model_dump_json(), result.created_at.isoformat()),
                )
        except sqlite3.Error as exc:
            raise StorageError(f"Failed to save {domain} plan {plan_id}: {exc}") from exc

    def get_replenishment_plan(self, plan_id: str) -> Optional[tuple[ReplenishmentPlanRequest, ReplenishmentPlanResult]]:
        row = self._get_plan_row(plan_id, "replenishment")
        if row is None:
            return None
        return (
            ReplenishmentPlanRequest.model_validate(json.loads(row["request_json"])),
            ReplenishmentPlanResult.model_validate(json.loads(row["result_json"])),
        )

    def get_routing_plan(self, plan_id: str) -> Optional[tuple[VehicleRoutingRequest, VehicleRoutingResult]]:
        row = self._get_plan_row(plan_id, "routing")
        if row is None:
            return None
        return (
            VehicleRoutingRequest.model_validate(json.loads(row["request_json"])),
            VehicleRoutingResult.model_validate(json.loads(row["result_json"])),
        )

    def get_network_plan(self, plan_id: str) -> Optional[tuple[NetworkOptimizationRequest, NetworkOptimizationResult]]:
        row = self._get_plan_row(plan_id, "network")
        if row is None:
            return None
        return (
            NetworkOptimizationRequest.model_validate(json.loads(row["request_json"])),
            NetworkOptimizationResult.model_validate(json.loads(row["result_json"])),
        )

    def _get_plan_row(self, plan_id: str, domain: str) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM plans WHERE plan_id = ? AND domain = ?", (plan_id, domain)
            ).fetchone()
        return row

    def get_plan_domain(self, plan_id: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute("SELECT domain FROM plans WHERE plan_id = ?", (plan_id,)).fetchone()
        return row["domain"] if row else None

    def count_plans(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM plans").fetchone()
        return row["c"]
