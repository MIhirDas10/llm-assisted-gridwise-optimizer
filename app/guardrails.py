"""Deterministic guardrails for operator-note directive interpretations.

This module is the trust boundary between the LLM interpreter and the optimizer.
It treats LLM output as untrusted structured data and re-validates every
machine-checkable rule from Section 04, 05, and 08 of the problem statement.

Validation rules:

- Each note_index must appear exactly once, in the order 0..N-1.
- directive_type must be one of the supported values.
- For no_op: applies must be False and structured_adjustment must be None.
- For every other directive: applies must be True and structured_adjustment
  must match the required shape for that directive.
- Every hours array must be a unique ascending list of integers 0..23.
- For solar_reduction: factor must be in [0, 1].
- For minimum_battery_reserve: minimum_energy_kwh must be finite, non-negative,
  and not exceed battery capacity.
- For max_grid_window: max_grid_kwh must be finite and non-negative.
- The LLM must not invent a directive type that is not in the supported set.

When any rule fails, validation stops. The API reports a controlled model-output
failure instead of silently changing a relevant directive into no_op.
"""

from __future__ import annotations

from math import isfinite
from typing import Any

from app.schemas import (
    Battery,
    DirectiveInterpretation,
    DirectiveType,
    HourEntry,
)

SUPPORTED_DIRECTIVE_TYPES: frozenset[DirectiveType] = frozenset(
    {
        "solar_reduction",
        "minimum_battery_reserve",
        "no_charge_window",
        "no_discharge_window",
        "max_grid_window",
        "no_op",
    }
)


class GuardrailViolation(Exception):
    """Raised when model output cannot be safely sent to the optimizer."""


def _is_hour_list(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    if not all(isinstance(item, int) and not isinstance(item, bool) for item in value):
        return False
    if any(item < 0 or item > 23 for item in value):
        return False
    if len(value) != len(set(value)):
        return False
    if value != sorted(value):
        return False
    return True


def _require_exact_keys(adjustment: dict[str, Any], expected: set[str]) -> None:
    if set(adjustment) != expected:
        raise _ShapeError(
            "structured_adjustment must contain exactly: " + ", ".join(sorted(expected))
        )


def _validate_no_op(
    item: DirectiveInterpretation, note_index: int
) -> DirectiveInterpretation:
    if item.directive_type != "no_op":
        raise _ShapeError("no_op must use directive_type='no_op'")
    if item.applies is not False:
        raise _ShapeError("no_op must have applies=False")
    if item.structured_adjustment is not None:
        raise _ShapeError("no_op must have structured_adjustment=None")
    if not item.explanation or not item.explanation.strip():
        raise _ShapeError("explanation must be a non-empty string")
    return DirectiveInterpretation(
        note_index=note_index,
        applies=False,
        directive_type="no_op",
        structured_adjustment=None,
        explanation=item.explanation.strip(),
    )


def _validate_solar_reduction(
    item: DirectiveInterpretation, note_index: int
) -> DirectiveInterpretation:
    adj = item.structured_adjustment
    if not isinstance(adj, dict):
        raise _ShapeError("solar_reduction requires structured_adjustment object")
    _require_exact_keys(adj, {"hours", "factor"})
    if not _is_hour_list(adj.get("hours")):
        raise _ShapeError("solar_reduction.hours must be unique ascending ints 0..23")
    factor = adj.get("factor")
    if not isinstance(factor, (int, float)) or isinstance(factor, bool):
        raise _ShapeError("solar_reduction.factor must be a number")
    if not isfinite(float(factor)) or not (0.0 <= float(factor) <= 1.0):
        raise _ShapeError("solar_reduction.factor must be within [0, 1]")
    clean_adj = {"hours": list(adj["hours"]), "factor": float(factor)}
    return DirectiveInterpretation(
        note_index=note_index,
        applies=True,
        directive_type="solar_reduction",
        structured_adjustment=clean_adj,
        explanation=item.explanation.strip(),
    )


def _validate_window(
    item: DirectiveInterpretation, note_index: int
) -> DirectiveInterpretation:
    adj = item.structured_adjustment
    if not isinstance(adj, dict):
        raise _ShapeError("window directive requires structured_adjustment object")
    _require_exact_keys(adj, {"hours"})
    if not _is_hour_list(adj.get("hours")):
        raise _ShapeError("window directive hours must be unique ascending ints 0..23")
    clean_adj = {"hours": list(adj["hours"])}
    return DirectiveInterpretation(
        note_index=note_index,
        applies=True,
        directive_type=item.directive_type,
        structured_adjustment=clean_adj,
        explanation=item.explanation.strip(),
    )


def _validate_min_battery_reserve(
    item: DirectiveInterpretation, note_index: int, battery: Battery
) -> DirectiveInterpretation:
    adj = item.structured_adjustment
    if not isinstance(adj, dict):
        raise _ShapeError("minimum_battery_reserve requires structured_adjustment")
    _require_exact_keys(adj, {"hours", "minimum_energy_kwh"})
    if not _is_hour_list(adj.get("hours")):
        raise _ShapeError(
            "minimum_battery_reserve.hours must be unique ascending ints 0..23"
        )
    value = adj.get("minimum_energy_kwh")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise _ShapeError("minimum_energy_kwh must be a number")
    value_f = float(value)
    if not isfinite(value_f):
        raise _ShapeError("minimum_energy_kwh must be finite")
    if value_f < 0:
        raise _ShapeError("minimum_energy_kwh must not be negative")
    if value_f > battery.capacity_kwh:
        raise _ShapeError(
            "minimum_energy_kwh must not exceed battery capacity"
        )
    clean_adj = {
        "hours": list(adj["hours"]),
        "minimum_energy_kwh": value_f,
    }
    return DirectiveInterpretation(
        note_index=note_index,
        applies=True,
        directive_type="minimum_battery_reserve",
        structured_adjustment=clean_adj,
        explanation=item.explanation.strip(),
    )


def _validate_max_grid_window(
    item: DirectiveInterpretation, note_index: int
) -> DirectiveInterpretation:
    adj = item.structured_adjustment
    if not isinstance(adj, dict):
        raise _ShapeError("max_grid_window requires structured_adjustment")
    _require_exact_keys(adj, {"hours", "max_grid_kwh"})
    if not _is_hour_list(adj.get("hours")):
        raise _ShapeError(
            "max_grid_window.hours must be unique ascending ints 0..23"
        )
    cap = adj.get("max_grid_kwh")
    if not isinstance(cap, (int, float)) or isinstance(cap, bool):
        raise _ShapeError("max_grid_kwh must be a number")
    cap_f = float(cap)
    if not isfinite(cap_f):
        raise _ShapeError("max_grid_kwh must be finite")
    if cap_f < 0:
        raise _ShapeError("max_grid_kwh must not be negative")
    clean_adj = {"hours": list(adj["hours"]), "max_grid_kwh": cap_f}
    return DirectiveInterpretation(
        note_index=note_index,
        applies=True,
        directive_type="max_grid_window",
        structured_adjustment=clean_adj,
        explanation=item.explanation.strip(),
    )


class _ShapeError(Exception):
    """Internal marker for a per-directive shape validation failure."""


_VALIDATORS = {
    "no_op": lambda item, idx, battery: _validate_no_op(item, idx),
    "solar_reduction": lambda item, idx, battery: _validate_solar_reduction(item, idx),
    "no_charge_window": lambda item, idx, battery: _validate_window(item, idx),
    "no_discharge_window": lambda item, idx, battery: _validate_window(item, idx),
    "minimum_battery_reserve": lambda item, idx, battery: _validate_min_battery_reserve(
        item, idx, battery
    ),
    "max_grid_window": lambda item, idx, battery: _validate_max_grid_window(item, idx),
}


def _validate_single(
    item: DirectiveInterpretation, note_index: int, battery: Battery
) -> DirectiveInterpretation:
    if item.note_index != note_index:
        raise _ShapeError(
            f"note_index {item.note_index} does not match expected {note_index}"
        )
    if item.directive_type not in SUPPORTED_DIRECTIVE_TYPES:
        raise _ShapeError(f"unsupported directive_type: {item.directive_type!r}")
    if not isinstance(item.applies, bool):
        raise _ShapeError("applies must be a boolean")
    if item.directive_type == "no_op":
        if item.applies is not False:
            raise _ShapeError("no_op must have applies=False")
    else:
        if item.applies is not True:
            raise _ShapeError("non-no_op directives must have applies=True")
        if item.structured_adjustment is None:
            raise _ShapeError("non-no_op directives require structured_adjustment")
    if not isinstance(item.explanation, str) or not item.explanation.strip():
        raise _ShapeError("explanation must be a non-empty string")

    validator = _VALIDATORS[item.directive_type]
    return validator(item, note_index, battery)


def apply_guardrails(
    interpretations: list[DirectiveInterpretation],
    battery: Battery,
    hours: list[HourEntry] | None = None,
) -> list[DirectiveInterpretation]:
    """Re-validate every interpretation and fail closed on malformed output."""
    expected_indexes = list(range(len(interpretations)))
    actual_indexes = [item.note_index for item in interpretations]
    if actual_indexes != expected_indexes:
        raise GuardrailViolation(
            "directive_interpretation must contain exactly one entry per note "
            "in note_index order"
        )

    cleaned: list[DirectiveInterpretation] = []
    for index, item in enumerate(interpretations):
        try:
            cleaned.append(_validate_single(item, index, battery))
        except _ShapeError as exc:
            raise GuardrailViolation(
                f"directive for note_index={index} failed validation: {exc}"
            ) from exc
    return cleaned
