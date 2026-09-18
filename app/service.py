from app.schemas import (
    HourlyPlanEntry,
    OptimizeEnergyRequest,
    OptimizeEnergyResponse,
)
from app.llm_interpreter import NoteInterpreter


def build_contract_response(
    payload: OptimizeEnergyRequest, interpreter: NoteInterpreter
) -> OptimizeEnergyResponse:
    """Interpret notes and return the temporary baseline plan used before Module 4."""
    directive_interpretation = interpreter.interpret_notes(
        payload.operator_notes, payload.battery
    )

    hourly_plan: list[HourlyPlanEntry] = []
    for hour in payload.hours:
        solar_used = min(hour.demand_kwh, hour.solar_kwh)
        grid_kwh = hour.demand_kwh - solar_used
        hourly_plan.append(
            HourlyPlanEntry(
                hour=hour.hour,
                grid_kwh=round(grid_kwh, 6),
                solar_used_kwh=round(solar_used, 6),
                battery_action="idle",
                battery_kwh=0,
                battery_energy_after_kwh=payload.battery.initial_energy_kwh,
            )
        )

    total_grid_kwh = round(sum(entry.grid_kwh for entry in hourly_plan), 6)
    total_cost_bdt = round(
        sum(entry.grid_kwh * hour.tariff_bdt_per_kwh for entry, hour in zip(hourly_plan, payload.hours)),
        6,
    )
    peak_grid_kwh = round(max(entry.grid_kwh for entry in hourly_plan), 6)

    return OptimizeEnergyResponse(
        scenario_id=payload.scenario_id,
        directive_interpretation=directive_interpretation,
        hourly_plan=hourly_plan,
        total_grid_kwh=total_grid_kwh,
        total_cost_bdt=total_cost_bdt,
        peak_grid_kwh=peak_grid_kwh,
        plan_summary=(
            "Module 2 response: operator notes were interpreted by the configured language model. "
            "The hourly schedule remains an idle-battery baseline until guardrails and optimization are added."
        ),
    )
