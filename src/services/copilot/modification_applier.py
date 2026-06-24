"""
What-if modification applier: takes the copilot's structured
WhatIfModification objects (already validated as well-formed by
CopilotService) and applies them to a copy of the original solver
request, producing a new request ready for re-solving.

This is intentionally simple dotted-path field assignment over the
existing Pydantic request models — it never executes arbitrary code,
and any modification that doesn't resolve to a real field on the
target model raises InvalidModificationError rather than silently
no-op-ing (ADR-004: every modification is auditable and schema-checked).
"""
from __future__ import annotations

import re

from src.domain.copilot_schemas import WhatIfModification
from src.domain.exceptions import InvalidModificationError

_PATH_SEGMENT_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)(\[(.+)\])?$")


def apply_modifications(request, modifications: list[WhatIfModification]):
    """
    Returns a new request object (of the same type as `request`) with
    every modification applied. Raises InvalidModificationError if any
    modification's field_path doesn't resolve to a real, settable field.
    """
    data = request.model_dump(mode="json")
    for mod in modifications:
        _apply_single_modification(data, mod)

    model_cls = type(request)
    try:
        return model_cls.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        raise InvalidModificationError(
            f"Applying modifications produced an invalid {model_cls.__name__}: {exc}"
        ) from exc


def _apply_single_modification(data: dict, mod: WhatIfModification) -> None:
    """
    Walks `mod.field_path` segment by segment. `cursor` always refers to
    the current dict/list we're indexing *into*; at each step we resolve
    one segment (a plain key, or a `key[index]` list lookup) and either
    descend further or, on the final segment, set the value.
    """
    segments = mod.field_path.split(".")
    cursor = data

    for i, segment in enumerate(segments):
        match = _PATH_SEGMENT_RE.match(segment)
        if not match:
            raise InvalidModificationError(f"Malformed field path segment: '{segment}' in '{mod.field_path}'")

        key, _, index_key = match.groups()
        is_last = i == len(segments) - 1

        if not isinstance(cursor, dict) or key not in cursor:
            raise InvalidModificationError(f"Field '{key}' not found while applying path '{mod.field_path}'")

        if index_key is not None:
            # This segment is e.g. "warehouses[WH-2]": cursor[key] must be a list;
            # resolve the indexed item, which becomes the new cursor.
            target_list = cursor[key]
            if not isinstance(target_list, list):
                raise InvalidModificationError(f"Expected a list at '{key}' for indexed path '{mod.field_path}'")
            item = _find_list_item(target_list, index_key, mod.field_path)
            if is_last:
                raise InvalidModificationError(
                    f"Path '{mod.field_path}' must end in a field name, not a bare list index/key lookup"
                )
            cursor = item
        elif is_last:
            # Plain final segment: set the value directly on the current cursor dict.
            _set_typed_value(cursor, key, mod.new_value, mod.field_path)
        else:
            # Plain intermediate segment: descend into the nested dict.
            cursor = cursor[key]


def _find_list_item(items: list, index_key: str, field_path: str):
    """
    Resolves `[KEY]` against a list of dict-like items. Tries a numeric
    index first; otherwise looks for an item whose first identifying
    field (warehouse_id/vehicle_id/sku/location_id) matches the key —
    this lets the copilot write human-readable paths like
    'warehouses[WH-2].is_active' instead of needing numeric indices.
    """
    if index_key.isdigit():
        idx = int(index_key)
        if idx >= len(items):
            raise InvalidModificationError(f"Index {idx} out of range for path '{field_path}'")
        return items[idx]

    id_fields = ("warehouse_id", "vehicle_id", "sku", "location_id", "stop_id")
    for item in items:
        if not isinstance(item, dict):
            continue
        for id_field in id_fields:
            if item.get(id_field) == index_key:
                return item

    raise InvalidModificationError(f"No item with identifier '{index_key}' found for path '{field_path}'")


def _set_typed_value(container: dict, key: str, raw_value: str, field_path: str) -> None:
    if key not in container:
        raise InvalidModificationError(f"Field '{key}' not found while applying path '{field_path}'")

    current = container[key]
    parsed = _coerce_to_matching_type(raw_value, current, field_path)
    container[key] = parsed


def _coerce_to_matching_type(raw_value: str, current_value, field_path: str):
    if isinstance(current_value, bool):
        lowered = raw_value.strip().lower()
        if lowered in ("true", "1", "yes"):
            return True
        if lowered in ("false", "0", "no"):
            return False
        raise InvalidModificationError(f"Could not parse '{raw_value}' as a boolean for path '{field_path}'")
    if isinstance(current_value, int):
        try:
            return int(float(raw_value))
        except ValueError as exc:
            raise InvalidModificationError(f"Could not parse '{raw_value}' as an int for path '{field_path}'") from exc
    if isinstance(current_value, float):
        try:
            return float(raw_value)
        except ValueError as exc:
            raise InvalidModificationError(f"Could not parse '{raw_value}' as a float for path '{field_path}'") from exc
    return raw_value
