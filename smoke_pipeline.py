"""End-to-end smoke test of the interpreter+guardrails+optimizer+replay pipeline."""

import json

from app.errors import LLMInvalidOutputError
from app.guardrails import apply_guardrails
from app.llm_interpreter import NoteInterpreter
from app.optimizer import optimize_schedule
from app.replay import replay_plan
from app.schemas import (
    Battery,
    DirectiveInterpretation,
    HourEntry,
    OptimizeEnergyRequest,
)


class StubInterpreter:
    def interpret_notes(self, notes, battery):  # type: ignore[no-untyped-def]
        return [
            DirectiveInterpretation(
                note_index=i,
                applies=False,
                directive_type="no_op",
                structured_adjustment=None,
                explanation=f"Note {i} ignored in smoke test.",
            )
            for i in range(len(notes))
        ]


def make_request() -> OptimizeEnergyRequest:
    hours = [
        HourEntry(
            hour=h,
            demand_kwh=5.0 if h < 8 or h >= 18 else 15.0,
            solar_kwh=0.0 if (h < 6 or h > 18) else (10.0 if h in (10, 11, 12) else 6.0),
            tariff_bdt_per_kwh=6.0 if 18 <= h or h < 9 else 12.0,
        )
        for h in range(24)
    ]
    battery = Battery(
        capacity_kwh=20.0,
        initial_energy_kwh=10.0,
        minimum_energy_kwh=2.0,
        max_charge_kwh_per_hour=5.0,
        max_discharge_kwh_per_hour=5.0,
    )
    return OptimizeEnergyRequest(
        scenario_id="SMOKE-01",
        operator_notes=["Run a normal day."],
        hours=hours,
        battery=battery,
    )


def main() -> None:
    payload = make_request()
    interp = StubInterpreter()
    raw = interp.interpret_notes(payload.operator_notes, payload.battery)
    safe = apply_guardrails(raw, payload.battery, hours=payload.hours)
    result = optimize_schedule(payload.hours, payload.battery, safe)
    totals = replay_plan(payload.hours, payload.battery, safe, result.plan)

    summary = {
        "scenario_id": payload.scenario_id,
        "total_grid_kwh": totals.total_grid_kwh,
        "total_cost_bdt": totals.total_cost_bdt,
        "peak_grid_kwh": totals.peak_grid_kwh,
        "first_three_plan": [
            {
                "hour": p.hour,
                "grid_kwh": p.grid_kwh,
                "solar_used_kwh": p.solar_used_kwh,
                "battery_action": p.battery_action,
                "battery_kwh": p.battery_kwh,
                "battery_energy_after_kwh": p.battery_energy_after_kwh,
            }
            for p in result.plan[:3]
        ],
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
