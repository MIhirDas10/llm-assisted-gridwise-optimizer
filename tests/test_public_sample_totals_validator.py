"""Validate the full pipeline against the public sample expected outputs.

Hidden tests are judged on a combination of:
  - directive interpretation semantics,
  - feasibility of the returned plan,
  - whether the plan's totals agree with the sample's
    `total_cost_bdt`, `total_grid_kwh`, `peak_grid_kwh`.

This test loops through every public sample case, rebuilds the canonical
`hourly_plan` from `expected_output.hourly_plan`, runs `replay_plan` over
it, and asserts the replayed totals match the sample's totals within
the Section 11.5 tolerance (0.01 kWh / 0.01 BDT).

It also confirms each sample's `directive_interpretation` parses cleanly
through `apply_guardrails` so the interpreter's structured output can be
fed into the optimizer without losing data.

Runs fully offline — no API key required.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.guardrails import apply_guardrails
from app.replay import replay_plan
from app.schemas import (
    Battery,
    DirectiveInterpretation,
    HourEntry,
    HourlyPlanEntry,
)


SAMPLE_FILE = Path(__file__).parents[1] / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"
TOLERANCE_KWH = 0.01
TOLERANCE_BDT = 0.01


def _load_cases() -> list[dict]:
    return json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))["cases"]


def _battery(case: dict) -> Battery:
    return Battery.model_validate(case["input"]["battery"])


def _hours(case: dict) -> list[HourEntry]:
    return [HourEntry.model_validate(entry) for entry in case["input"]["hours"]]


def _plan(case: dict) -> list[HourlyPlanEntry]:
    return [HourlyPlanEntry.model_validate(entry) for entry in case["expected_output"]["hourly_plan"]]


def _interpretations(case: dict) -> list[DirectiveInterpretation]:
    return [
        DirectiveInterpretation.model_validate(entry)
        for entry in case["expected_output"]["directive_interpretation"]
    ]


CASES = _load_cases()
CASE_IDS = [case["id"] for case in CASES]


# ---------------------------------------------------------------------------
# Structural smoke checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_sample_directive_interpretations_round_trip_through_guardrails(case: dict) -> None:
    interpretations = _interpretations(case)
    battery = _battery(case)
    cleaned = apply_guardrails(interpretations, battery)
    assert len(cleaned) == len(interpretations)
    for cleaned_entry, original_entry in zip(cleaned, interpretations):
        assert cleaned_entry.note_index == original_entry.note_index
        assert cleaned_entry.directive_type == original_entry.directive_type
        assert cleaned_entry.applies == original_entry.applies
        assert cleaned_entry.structured_adjustment == original_entry.structured_adjustment


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_sample_hourly_plan_covers_24_hours_in_order(case: dict) -> None:
    plan = _plan(case)
    assert len(plan) == 24
    assert [entry.hour for entry in plan] == list(range(24))


# ---------------------------------------------------------------------------
# Replay the canonical plan and verify totals match the sample
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_replay_totals_agree_with_sample(case: dict) -> None:
    interpretations = _interpretations(case)
    battery = _battery(case)
    hours = _hours(case)
    plan = _plan(case)

    totals = replay_plan(hours, battery, interpretations, plan)

    expected_total_grid = float(case["expected_output"]["total_grid_kwh"])
    expected_total_cost = float(case["expected_output"]["total_cost_bdt"])
    expected_peak = float(case["expected_output"]["peak_grid_kwh"])

    assert abs(totals.total_grid_kwh - expected_total_grid) <= TOLERANCE_KWH, (
        f"{case['id']}: total_grid_kwh {totals.total_grid_kwh} "
        f"!= sample {expected_total_grid}"
    )
    assert abs(totals.total_cost_bdt - expected_total_cost) <= TOLERANCE_BDT, (
        f"{case['id']}: total_cost_bdt {totals.total_cost_bdt} "
        f"!= sample {expected_total_cost}"
    )
    assert abs(totals.peak_grid_kwh - expected_peak) <= TOLERANCE_KWH, (
        f"{case['id']}: peak_grid_kwh {totals.peak_grid_kwh} "
        f"!= sample {expected_peak}"
    )


# ---------------------------------------------------------------------------
# Hidden-test shaped check: the sample must be feasible
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_canonical_plan_satisfies_all_section_09_invariants(case: dict) -> None:
    """The canonical plan must satisfy every directive constraint and the
    battery transition / end-of-day neutrality invariants."""
    interpretations = _interpretations(case)
    battery = _battery(case)
    hours = _hours(case)
    plan = _plan(case)

    # Will raise ReplayViolation if any invariant fails.
    replay_plan(hours, battery, interpretations, plan)

    # End-of-day battery neutrality.
    by_hour = {entry.hour: entry for entry in plan}
    assert (
        abs(by_hour[23].battery_energy_after_kwh - battery.initial_energy_kwh)
        <= TOLERANCE_KWH
    ), f"{case['id']}: end-of-day neutrality violated"


# ---------------------------------------------------------------------------
# Sanity: every sample exposes non-zero totals (guards against empty fixtures)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_sample_exposes_non_trivial_totals(case: dict) -> None:
    expected = case["expected_output"]
    assert float(expected["total_grid_kwh"]) > 0
    assert float(expected["total_cost_bdt"]) > 0
    assert float(expected["peak_grid_kwh"]) > 0
