from app.schemas import (
    DirectiveInterpretation,
    HourlyPlanEntry,
    OptimizeEnergyRequest,
    OptimizeEnergyResponse,
)


def build_contract_response(payload: OptimizeEnergyRequest) -> OptimizeEnergyResponse:
    """Return a valid response shape for module 1 before LLM/optimizer modules land."""
    directive_interpretation = [
        DirectiveInterpretation(
            note_index=index,
            applies=False,
            directive_type="no_op",
            structured_adjustment=None,
            explanation="Module 1 placeholder: operator-note interpretation is implemented in module 2.",
        )
        for index, _note in enumerate(payload.operator_notes)
    ]

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
            "Module 1 contract response: serves the required API shape with an idle-battery "
            "baseline plan. LLM interpretation, guardrails, and cost optimization are added in later modules."
        ),
    )

