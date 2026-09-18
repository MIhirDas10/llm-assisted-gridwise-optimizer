"""Service layer: glue the interpreter, guardrails, optimizer, and replay."""

from app.errors import LLMInvalidOutputError, OptimizationError_, ReplayViolationError
from app.guardrails import GuardrailViolation, apply_guardrails
from app.llm_interpreter import NoteInterpreter
from app.optimizer import optimize_schedule
from app.replay import replay_plan
from app.schemas import (
    HourlyPlanEntry,
    OptimizeEnergyRequest,
    OptimizeEnergyResponse,
)


def build_contract_response(
    payload: OptimizeEnergyRequest, interpreter: NoteInterpreter
) -> OptimizeEnergyResponse:
    """Interpret notes, enforce guardrails, optimize, replay, return response."""
    raw_interpretations = interpreter.interpret_notes(
        payload.operator_notes, payload.battery
    )
    try:
        interpretations = apply_guardrails(
            raw_interpretations, payload.battery, hours=payload.hours
        )
    except GuardrailViolation as exc:
        raise LLMInvalidOutputError() from exc

    try:
        optimization = optimize_schedule(
            payload.hours, payload.battery, interpretations
        )
    except Exception as exc:  # noqa: BLE001 - re-raised as typed error
        raise OptimizationError_(str(exc)) from exc

    try:
        totals = replay_plan(
            payload.hours, payload.battery, interpretations, optimization.plan
        )
    except Exception as exc:  # noqa: BLE001 - re-raised as typed error
        raise ReplayViolationError(str(exc)) from exc

    plan_summary = (
        f"24-hour schedule solved via LP (HiGHS). "
        f"Grid={totals.total_grid_kwh:.3f} kWh, "
        f"Cost={totals.total_cost_bdt:.2f} BDT, "
        f"Peak={totals.peak_grid_kwh:.3f} kWh."
    )

    return OptimizeEnergyResponse(
        scenario_id=payload.scenario_id,
        directive_interpretation=interpretations,
        hourly_plan=optimization.plan,
        total_grid_kwh=totals.total_grid_kwh,
        total_cost_bdt=totals.total_cost_bdt,
        peak_grid_kwh=totals.peak_grid_kwh,
        plan_summary=plan_summary,
    )


__all__ = [
    "build_contract_response",
    "HourlyPlanEntry",
    "OptimizeEnergyRequest",
    "OptimizeEnergyResponse",
]
