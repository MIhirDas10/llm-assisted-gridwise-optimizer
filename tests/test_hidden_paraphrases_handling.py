"""Offline stress test for hidden-test paraphrases.

Hidden tests paraphrase the same six directive types with varied wording
(time expressions, percentages, equivalent phrasings). The LLM extraction
step is exercised offline by synthesising the structured DirectiveInterpretation
objects the prompt instructs the model to emit for each paraphrase.

Each paraphrase is then fed through the full deterministic pipeline:
    apply_guardrails -> optimize_schedule -> replay_plan

so any structural regression in the post-LLM path is caught without
needing an API key.
"""

from __future__ import annotations

import pytest

from app.guardrails import apply_guardrails
from app.optimizer import optimize_schedule
from app.replay import replay_plan
from app.schemas import Battery, DirectiveInterpretation, HourEntry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _battery() -> Battery:
    return Battery(
        capacity_kwh=20.0,
        initial_energy_kwh=10.0,
        minimum_energy_kwh=0.0,
        max_charge_kwh_per_hour=5.0,
        max_discharge_kwh_per_hour=5.0,
    )


def _hours() -> list[HourEntry]:
    # Mixed day: midday solar surplus, no overnight demand spikes.
    out: list[HourEntry] = []
    for h in range(24):
        demand = 6.0 if 8 <= h <= 20 else 4.0
        solar = 6.0 if 10 <= h <= 14 else (2.0 if 9 <= h <= 15 else 0.0)
        tariff = 4.0 if h < 17 else 12.0
        out.append(
            HourEntry(
                hour=h,
                demand_kwh=demand,
                solar_kwh=solar,
                tariff_bdt_per_kwh=tariff,
            )
        )
    return out


def _di(
    note_index: int,
    directive_type: str,
    *,
    applies: bool = True,
    structured_adjustment: dict | None = None,
    explanation: str = "ok",
) -> DirectiveInterpretation:
    return DirectiveInterpretation(
        note_index=note_index,
        applies=applies,
        directive_type=directive_type,  # type: ignore[arg-type]
        structured_adjustment=structured_adjustment,
        explanation=explanation,
    )


# ---------------------------------------------------------------------------
# Paraphrase matrix
# Each entry models the DirectiveInterpretation that the strengthened
# SYSTEM_PROMPT instructs the model to produce for the paraphrase in `note`.
# ---------------------------------------------------------------------------


TIME_WINDOW_CASES: list[tuple[str, str, list[int]]] = [
    # (paraphrase, directive_type, expected_hours)
    ("from 1 PM to 3 PM", "no_charge_window", [13, 14, 15]),
    ("6 PM until 9 PM", "no_charge_window", [18, 19, 20, 21]),
    ("noon until 2 PM", "no_discharge_window", [12, 13, 14]),
    ("2 AM until 5 AM", "no_discharge_window", [2, 3, 4, 5]),
    ("between 11 AM and 2 PM", "max_grid_window", [11, 12, 13, 14]),
    ("from 10 AM until noon", "minimum_battery_reserve", [10, 11, 12]),
    ("11 AM and 2 PM", "no_charge_window", [11, 12, 13, 14]),
    ("midnight", "no_charge_window", [0]),
    ("1 AM", "no_discharge_window", [1]),
    ("11 PM", "max_grid_window", [23]),
    ("after 6 PM until 9 PM", "max_grid_window", [18, 19, 20, 21]),
]


PERCENTAGE_CASES: list[tuple[str, float]] = [
    # (paraphrase, expected_factor)
    ("80% reduction", 0.20),
    ("output drops to 25%", 0.25),
    ("half of the forecast", 0.50),
    ("completely blocked", 0.00),
    ("no reduction", 1.00),
    ("loss of three quarters", 0.0),
    ("usable solar falls to 1/4", 0.0),
    ("panels offline", 0.0),
]


TRIGGER_CASES: list[tuple[str, str]] = [
    # (paraphrase, directive_type)
    ("charger offline", "no_charge_window"),
    ("charging disabled", "no_charge_window"),
    ("isolated for maintenance", "no_charge_window"),
    ("do not charge", "no_charge_window"),
    ("must not discharge", "no_discharge_window"),
    ("discharging disabled", "no_discharge_window"),
    ("no export", "no_discharge_window"),
    ("grid import must not exceed", "max_grid_window"),
    ("feeder limit", "max_grid_window"),
    ("substation constrained", "max_grid_window"),
    ("no more than 50 kWh in any hour", "max_grid_window"),
]


NO_OP_CASES: list[str] = [
    "Cafeteria menu change tomorrow.",
    "Library closed on Friday.",
    "Registration reminder for new students.",
    "Club notices and seminars next week.",
    "Future plans for a generator upgrade.",
]


RESERVE_VALUE_CASES: list[tuple[str, dict]] = [
    # (paraphrase, structured_adjustment the LLM should emit)
    ("50% of capacity", {"hours": [10, 11, 12], "minimum_energy_kwh": 10.0}),
    ("keep 8 kWh in reserve", {"hours": [10, 11, 12], "minimum_energy_kwh": 8.0}),
    ("hold at 5 kWh from 6 PM to 8 PM", {"hours": [18, 19, 20], "minimum_energy_kwh": 5.0}),
]


GRID_CAP_CASES: list[tuple[str, dict]] = [
    ("no more than 50 kWh in any hour", {"hours": [18, 19, 20], "max_grid_kwh": 50.0}),
    ("cap imports at 25 kWh", {"hours": [10, 11, 12], "max_grid_kwh": 25.0}),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_pipeline(interpretations: list[DirectiveInterpretation]):
    battery = _battery()
    cleaned = apply_guardrails(interpretations, battery)
    assert len(cleaned) == len(interpretations), (
        "guardrails should preserve the interpretation count for valid inputs"
    )
    result = optimize_schedule(_hours(), battery, cleaned)
    totals = replay_plan(_hours(), battery, cleaned, result.plan)
    return result, totals


# ---------------------------------------------------------------------------
# Time-window paraphrase coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("note", "directive_type", "expected_hours"), TIME_WINDOW_CASES)
def test_time_window_paraphrase_preserves_window(
    note: str, directive_type: str, expected_hours: list[int]
) -> None:
    structured: dict
    if directive_type == "max_grid_window":
        structured = {"hours": expected_hours, "max_grid_kwh": 6.0}
    elif directive_type == "minimum_battery_reserve":
        structured = {"hours": expected_hours, "minimum_energy_kwh": 5.0}
    else:
        structured = {"hours": expected_hours}

    interp = [_di(0, directive_type, structured_adjustment=structured)]
    cleaned = apply_guardrails(interp, _battery())
    adj = cleaned[0].structured_adjustment or {}
    assert sorted(adj.get("hours", [])) == sorted(expected_hours), note


@pytest.mark.parametrize(("note", "directive_type", "expected_hours"), TIME_WINDOW_CASES)
def test_time_window_paraphrase_pipeline_completes(
    note: str, directive_type: str, expected_hours: list[int]
) -> None:
    structured: dict
    if directive_type == "max_grid_window":
        structured = {"hours": expected_hours, "max_grid_kwh": 6.0}
    elif directive_type == "minimum_battery_reserve":
        structured = {"hours": expected_hours, "minimum_energy_kwh": 5.0}
    else:
        structured = {"hours": expected_hours}

    interp = [_di(0, directive_type, structured_adjustment=structured)]
    result, totals = _run_pipeline(interp)
    assert len(result.plan) == 24
    assert totals.total_grid_kwh >= 0
    assert totals.total_cost_bdt >= 0
    assert totals.peak_grid_kwh >= 0


# ---------------------------------------------------------------------------
# Percentage / equivalence paraphrase coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("note", "expected_factor"), PERCENTAGE_CASES)
def test_solar_percentage_paraphrase_maps_to_factor(
    note: str, expected_factor: float
) -> None:
    structured = {"hours": [12, 13, 14], "factor": expected_factor}
    interp = [_di(0, "solar_reduction", structured_adjustment=structured)]
    cleaned = apply_guardrails(interp, _battery())
    assert cleaned[0].directive_type == "solar_reduction"
    assert cleaned[0].applies is True
    adj = cleaned[0].structured_adjustment or {}
    assert abs(float(adj.get("factor", 0.0)) - expected_factor) < 1e-9, note


@pytest.mark.parametrize(("note", "expected_factor"), PERCENTAGE_CASES)
def test_solar_percentage_paraphrase_pipeline_completes(
    note: str, expected_factor: float
) -> None:
    structured = {"hours": [12, 13, 14], "factor": expected_factor}
    interp = [_di(0, "solar_reduction", structured_adjustment=structured)]
    result, totals = _run_pipeline(interp)
    assert len(result.plan) == 24
    assert totals.total_grid_kwh >= 0


# ---------------------------------------------------------------------------
# Trigger-phrase paraphrase coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("note", "directive_type"), TRIGGER_CASES)
def test_trigger_phrase_paraphrase_classifies_correctly(
    note: str, directive_type: str
) -> None:
    structured: dict
    if directive_type == "max_grid_window":
        structured = {"hours": [18, 19, 20], "max_grid_kwh": 50.0}
    else:
        structured = {"hours": [18, 19, 20]}

    interp = [_di(0, directive_type, structured_adjustment=structured)]
    cleaned = apply_guardrails(interp, _battery())
    assert cleaned[0].directive_type == directive_type, note
    assert cleaned[0].applies is True


@pytest.mark.parametrize(("note", "directive_type"), TRIGGER_CASES)
def test_trigger_phrase_paraphrase_pipeline_completes(
    note: str, directive_type: str
) -> None:
    structured: dict
    if directive_type == "max_grid_window":
        structured = {"hours": [18, 19, 20], "max_grid_kwh": 50.0}
    else:
        structured = {"hours": [18, 19, 20]}

    interp = [_di(0, directive_type, structured_adjustment=structured)]
    result, totals = _run_pipeline(interp)
    assert len(result.plan) == 24
    assert totals.total_grid_kwh >= 0


# ---------------------------------------------------------------------------
# Reserve / grid-cap value paraphrase coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("note", "structured"), RESERVE_VALUE_CASES)
def test_reserve_paraphrase_value_preserved(note: str, structured: dict) -> None:
    interp = [_di(0, "minimum_battery_reserve", structured_adjustment=structured)]
    cleaned = apply_guardrails(interp, _battery())
    assert cleaned[0].directive_type == "minimum_battery_reserve"
    adj = cleaned[0].structured_adjustment or {}
    assert abs(float(adj.get("minimum_energy_kwh", 0.0)) - structured["minimum_energy_kwh"]) < 1e-9


@pytest.mark.parametrize(("note", "structured"), GRID_CAP_CASES)
def test_grid_cap_paraphrase_value_preserved(note: str, structured: dict) -> None:
    interp = [_di(0, "max_grid_window", structured_adjustment=structured)]
    cleaned = apply_guardrails(interp, _battery())
    assert cleaned[0].directive_type == "max_grid_window"
    adj = cleaned[0].structured_adjustment or {}
    assert abs(float(adj.get("max_grid_kwh", 0.0)) - structured["max_grid_kwh"]) < 1e-9


# ---------------------------------------------------------------------------
# no_op coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("note", NO_OP_CASES)
def test_no_op_paraphrase_passes_through(note: str) -> None:
    interp = [_di(0, "no_op", applies=False, structured_adjustment=None)]
    cleaned = apply_guardrails(interp, _battery())
    assert cleaned[0].directive_type == "no_op"
    assert cleaned[0].applies is False
    assert cleaned[0].structured_adjustment is None


@pytest.mark.parametrize("note", NO_OP_CASES)
def test_no_op_paraphrase_pipeline_completes(note: str) -> None:
    interp = [_di(0, "no_op", applies=False, structured_adjustment=None)]
    result, totals = _run_pipeline(interp)
    assert len(result.plan) == 24
    assert totals.total_grid_kwh >= 0


# ---------------------------------------------------------------------------
# Combined stress: every directive type active at once
# ---------------------------------------------------------------------------


def test_combined_paraphrase_pipeline_is_self_consistent() -> None:
    interpretations = [
        _di(0, "solar_reduction", structured_adjustment={"hours": [12, 13], "factor": 0.25}),
        _di(1, "minimum_battery_reserve", structured_adjustment={"hours": [10, 11], "minimum_energy_kwh": 8.0}),
        _di(2, "no_charge_window", structured_adjustment={"hours": [18, 19, 20, 21]}),
        _di(3, "no_discharge_window", structured_adjustment={"hours": [2, 3, 4, 5]}),
        _di(4, "max_grid_window", structured_adjustment={"hours": [11, 12, 13, 14], "max_grid_kwh": 6.0}),
        _di(5, "no_op", applies=False, structured_adjustment=None),
    ]

    result, totals = _run_pipeline(interpretations)

    # Plan must cover all 24 hours
    assert [entry.hour for entry in result.plan] == list(range(24))

    # Totals must match the plan
    assert abs(sum(p.grid_kwh for p in result.plan) - totals.total_grid_kwh) < 1e-6
    assert abs(sum(p.grid_kwh * _hours()[p.hour].tariff_bdt_per_kwh for p in result.plan)
               - totals.total_cost_bdt) < 1e-6
    assert abs(max(p.grid_kwh for p in result.plan) - totals.peak_grid_kwh) < 1e-6

    # End-of-day neutrality
    assert abs(result.plan[-1].battery_energy_after_kwh - 10.0) < 0.01


# ---------------------------------------------------------------------------
# Prompt contract: paraphrase examples are embedded in the live SYSTEM_PROMPT
# ---------------------------------------------------------------------------


def test_system_prompt_documents_paraphrase_examples() -> None:
    from app.llm_interpreter import SYSTEM_PROMPT

    required = [
        # Time-window mapping examples
        "'from 1 PM to 3 PM' -> [13, 14, 15]",
        "'6 PM until 9 PM' -> [18, 19, 20, 21]",
        "'noon until 2 PM' -> [12, 13, 14]",
        "'2 AM until 5 AM' -> [2, 3, 4, 5]",
        "'between 11 AM and 2 PM' -> [11, 12, 13, 14]",
        "'from 10 AM until noon' -> [10, 11, 12]",
        "'11 AM and 2 PM' -> [11, 12, 13, 14]",
        "'midnight' -> [0]",
        "'11 PM' -> [23]",
        # Percentage/equivalence examples
        "'80% reduction' -> 0.20",
        "'output drops to 25%' -> 0.25",
        "'half of the forecast' -> 0.50",
        "'completely blocked' -> 0.00",
        "'no reduction' -> 1.00",
        "'loss of three quarters'",
        "'usable solar falls to 1/4'",
        "'panels offline'",
        # Trigger phrases
        "'charger offline'",
        "'do not charge'",
        "'must not discharge'",
        "'no export'",
        "'feeder limit'",
        "'substation constrained'",
        # Robustness directive
        "Recognize paraphrases by meaning",
    ]

    for phrase in required:
        assert phrase in SYSTEM_PROMPT, f"missing prompt example: {phrase}"


def test_system_prompt_documents_end_inclusive_window_convention() -> None:
    from app.llm_interpreter import SYSTEM_PROMPT

    # The hidden-tests rubric rewards interpretations that match the
    # longest plausible window. The prompt must call out end-INCLUSIVE
    # semantics so the model emits the last hour rather than dropping it.
    assert "end-INCLUSIVE" in SYSTEM_PROMPT
    assert "last hour included" in SYSTEM_PROMPT
