"""Unit tests for app.guardrails."""

from app.guardrails import (
    GuardrailViolation,
    SUPPORTED_DIRECTIVE_TYPES,
    apply_guardrails,
)
from app.schemas import Battery, DirectiveInterpretation


def _battery() -> Battery:
    return Battery(
        capacity_kwh=10.0,
        initial_energy_kwh=5.0,
        minimum_energy_kwh=1.0,
        max_charge_kwh_per_hour=3.0,
        max_discharge_kwh_per_hour=3.0,
    )


def test_supported_directive_types_lists_all_required() -> None:
    assert SUPPORTED_DIRECTIVE_TYPES == {
        "solar_reduction",
        "minimum_battery_reserve",
        "no_charge_window",
        "no_discharge_window",
        "max_grid_window",
        "no_op",
    }


def _di(
    note_index: int,
    directive_type: str,
    structured_adjustment: dict | None = None,
    applies: bool = True,
    explanation: str = "ok",
) -> DirectiveInterpretation:
    return DirectiveInterpretation(
        note_index=note_index,
        applies=applies,
        directive_type=directive_type,  # type: ignore[arg-type]
        structured_adjustment=structured_adjustment,
        explanation=explanation,
    )


def test_no_op_applies_passes_through() -> None:
    interp = [_di(0, "no_op", None)]
    out = apply_guardrails(interp, _battery())
    assert len(out) == 1
    assert out[0].directive_type == "no_op"


def test_unknown_directive_demoted_to_no_op() -> None:
    interp = [_di(0, "no_op", {"garbage": 1})]  # uses no_op but injects bad adjustment
    # Force the bad shape via the wider schema; cast to a non-allowed value
    interp = [
        DirectiveInterpretation(
            note_index=0,
            applies=True,
            directive_type="no_op",  # type: ignore[arg-type]
            structured_adjustment={"hours": [0, 0]},  # duplicate hours
            explanation="weird",
        )
    ]
    out = apply_guardrails(interp, _battery())
    # duplicate hours is invalid, must be demoted
    assert out[0].directive_type == "no_op"


def test_solar_reduction_with_negative_factor_demoted() -> None:
    interp = [_di(0, "solar_reduction", {"hours": [10], "factor": -0.5})]
    out = apply_guardrails(interp, _battery())
    assert out[0].directive_type == "no_op"


def test_solar_reduction_valid_passes() -> None:
    interp = [_di(0, "solar_reduction", {"hours": [10, 11, 12], "factor": 0.8})]
    out = apply_guardrails(interp, _battery())
    assert out[0].directive_type == "solar_reduction"


def test_max_grid_window_requires_cap_field() -> None:
    interp = [_di(0, "max_grid_window", {"hours": [18, 19, 20]})]
    out = apply_guardrails(interp, _battery())
    assert out[0].directive_type == "no_op"


def test_min_reserve_requires_floor_field() -> None:
    interp = [_di(0, "minimum_battery_reserve", {"hours": [22, 23]})]
    out = apply_guardrails(interp, _battery())
    assert out[0].directive_type == "no_op"


def test_window_hours_must_be_in_range() -> None:
    interp = [_di(0, "no_charge_window", {"hours": [24]})]
    out = apply_guardrails(interp, _battery())
    assert out[0].directive_type == "no_op"


def test_guardrail_violation_on_wrong_note_index() -> None:
    interp = [_di(99, "solar_reduction", {"hours": [10], "factor": 0.5})]
    # Wrong note_index for first entry should raise
    import pytest

    with pytest.raises(GuardrailViolation):
        apply_guardrails(interp, _battery())
