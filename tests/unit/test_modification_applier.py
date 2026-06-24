"""
Unit tests for src/services/copilot/modification_applier.py.

This module's dotted-path traversal logic had a real bug found and
fixed during development (conflating the "descend into nested dict" and
"set final field" cases when an indexed list lookup was followed by a
plain field) — these tests specifically exercise that exact scenario.
"""
from __future__ import annotations

import pytest

from src.domain.copilot_schemas import OptimizationDomain, WhatIfModification
from src.domain.exceptions import InvalidModificationError
from src.services.copilot.modification_applier import apply_modifications


def _mod(field_path: str, new_value: str) -> WhatIfModification:
    return WhatIfModification(
        target_domain=OptimizationDomain.NETWORK, field_path=field_path, new_value=new_value, rationale="test"
    )


class TestIndexedListModification:
    def test_close_warehouse_by_identifier(self, sample_network_request):
        mod = _mod("warehouses[WH-2].is_active", "false")
        updated = apply_modifications(sample_network_request, [mod])

        wh2 = next(w for w in updated.warehouses if w.warehouse_id == "WH-2")
        wh1 = next(w for w in updated.warehouses if w.warehouse_id == "WH-1")
        assert wh2.is_active is False
        assert wh1.is_active is True

    def test_close_warehouse_by_numeric_index(self, sample_network_request):
        mod = _mod("warehouses[1].is_active", "false")
        updated = apply_modifications(sample_network_request, [mod])
        assert updated.warehouses[1].is_active is False

    def test_modify_capacity_with_int_coercion(self, sample_network_request):
        mod = _mod("warehouses[WH-1].capacity_units", "999")
        updated = apply_modifications(sample_network_request, [mod])
        wh1 = next(w for w in updated.warehouses if w.warehouse_id == "WH-1")
        assert wh1.capacity_units == 999
        assert isinstance(wh1.capacity_units, int)

    def test_unknown_identifier_raises(self, sample_network_request):
        mod = _mod("warehouses[WH-DOES-NOT-EXIST].is_active", "false")
        with pytest.raises(InvalidModificationError):
            apply_modifications(sample_network_request, [mod])


class TestTopLevelModification:
    def test_modify_top_level_bool_field(self, sample_network_request):
        mod = _mod("allow_unmet_demand", "true")
        updated = apply_modifications(sample_network_request, [mod])
        assert updated.allow_unmet_demand is True

    def test_modify_top_level_float_field(self, sample_replenishment_request):
        mod = WhatIfModification(
            target_domain=OptimizationDomain.REPLENISHMENT,
            field_path="budget_constraint", new_value="5000", rationale="test",
        )
        updated = apply_modifications(sample_replenishment_request, [mod])
        assert updated.budget_constraint == 5000.0
        assert isinstance(updated.budget_constraint, float)

    def test_unknown_top_level_field_raises(self, sample_network_request):
        mod = _mod("totally_made_up_field", "123")
        with pytest.raises(InvalidModificationError):
            apply_modifications(sample_network_request, [mod])


class TestMultipleModifications:
    def test_applies_all_modifications_in_sequence(self, sample_network_request):
        mods = [_mod("warehouses[WH-1].is_active", "false"), _mod("allow_unmet_demand", "true")]
        updated = apply_modifications(sample_network_request, mods)
        wh1 = next(w for w in updated.warehouses if w.warehouse_id == "WH-1")
        assert wh1.is_active is False
        assert updated.allow_unmet_demand is True


class TestMalformedPaths:
    def test_malformed_segment_raises(self, sample_network_request):
        mod = _mod("warehouses[unclosed", "false")
        with pytest.raises(InvalidModificationError):
            apply_modifications(sample_network_request, [mod])

    def test_path_ending_in_bare_index_raises(self, sample_network_request):
        mod = _mod("warehouses[WH-1]", "false")
        with pytest.raises(InvalidModificationError):
            apply_modifications(sample_network_request, [mod])
