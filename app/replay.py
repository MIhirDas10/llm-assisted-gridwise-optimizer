"""Replay validator: re-derive Section 09 invariants from a returned hourly_plan.

The judge independently replays the schedule hour by hour using the effective
solar and the interpreter's directives. This module performs the same checks
deterministically so the service can refuse to return a plan that the judge
would reject.

Tolerance: absolute differences up to TOLERANCE_KWH / TOLERANCE_BDT are
considered equivalent to the canonical Section 11.5 value of 0.01.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas import (
    Battery,
    DirectiveInterpretation,
    HourEntry,
    HourlyPlanEntry,
)


TOLERANCE_KWH: float = 0.01
TOLERANCE_BDT: float = 0.01


class ReplayViolation(Exception):
    """Raised when a returned hourly_plan violates the Section 09 invariants."""


@dataclass(frozen=True)
class ReplayTotals:
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float


def _effective_solar_map(
    hours: list[HourEntry], interpretations: list[DirectiveInterpretation]
) -> dict[int, float]:
    factors: dict[int, float] = {}
    for entry in interpretations:
        if entry.directive_type != "solar_reduction" or not entry.applies:
            continue
        adj = entry.structured_adjustment or {}
        factor = float(adj.get("factor", 1.0))
        for hour in adj.get("hours", []):
            factors[hour] = factor
    return {
        h.hour: round(float(h.solar_kwh) * factors.get(h.hour, 1.0), 9)
        for h in hours
    }


def _directive_hours(
    interpretations: list[DirectiveInterpretation], directive_type: str
) -> set[int]:
    out: set[int] = set()
    for entry in interpretations:
        if entry.directive_type != directive_type or not entry.applies:
            continue
        adj = entry.structured_adjustment or {}
        for hour in adj.get("hours", []):
            out.add(int(hour))
    return out


def _reserve_map(
    interpretations: list[DirectiveInterpretation],
) -> dict[int, float]:
    out: dict[int, float] = {}
    for entry in interpretations:
        if entry.directive_type != "minimum_battery_reserve" or not entry.applies:
            continue
        adj = entry.structured_adjustment or {}
        floor = float(adj.get("minimum_energy_kwh", 0.0))
        for hour in adj.get("hours", []):
            h = int(hour)
            out[h] = max(out.get(h, 0.0), floor)
    return out


def _max_grid_map(
    interpretations: list[DirectiveInterpretation],
) -> dict[int, float]:
    out: dict[int, float] = {}
    for entry in interpretations:
        if entry.directive_type != "max_grid_window" or not entry.applies:
            continue
        adj = entry.structured_adjustment or {}
        cap = float(adj.get("max_grid_kwh", 0.0))
        for hour in adj.get("hours", []):
            h = int(hour)
            out[h] = min(out.get(h, cap), cap) if h in out else cap
    return out


def replay_plan(
    hours: list[HourEntry],
    battery: Battery,
    interpretations: list[DirectiveInterpretation],
    plan: list[HourlyPlanEntry],
) -> ReplayTotals:
    """Verify the plan satisfies every Section 09 invariant. Return totals."""
    if len(plan) != 24:
        raise ReplayViolation(
            f"hourly_plan must contain exactly 24 entries; got {len(plan)}"
        )
    plan_hours = sorted(entry.hour for entry in plan)
    if plan_hours != list(range(24)):
        raise ReplayViolation("hourly_plan must cover hours 0..23 in order")

    effective_solar = _effective_solar_map(hours, interpretations)
    no_charge_hours = _directive_hours(interpretations, "no_charge_window")
    no_discharge_hours = _directive_hours(interpretations, "no_discharge_window")
    reserve_map = _reserve_map(interpretations)
    max_grid_map = _max_grid_map(interpretations)

    plan_by_hour = {entry.hour: entry for entry in plan}
    energy_before = float(battery.initial_energy_kwh)
    total_grid = 0.0
    total_cost = 0.0
    peak_grid = 0.0

    for hour_entry in hours:
        h = hour_entry.hour
        plan_entry = plan_by_hour[h]

        if plan_entry.hour != h:
            raise ReplayViolation(f"plan hour mismatch at {h}")

        grid = float(plan_entry.grid_kwh)
        solar_used = float(plan_entry.solar_used_kwh)
        action = plan_entry.battery_action
        magnitude = float(plan_entry.battery_kwh)
        energy_after = float(plan_entry.battery_energy_after_kwh)

        if grid < -TOLERANCE_KWH:
            raise ReplayViolation(f"hour {h}: grid_kwh must be non-negative")
        if solar_used < -TOLERANCE_KWH:
            raise ReplayViolation(f"hour {h}: solar_used_kwh must be non-negative")
        if action not in {"charge", "discharge", "idle"}:
            raise ReplayViolation(f"hour {h}: invalid battery_action {action!r}")
        if action == "idle" and abs(magnitude) > TOLERANCE_KWH:
            raise ReplayViolation(
                f"hour {h}: battery_kwh must be 0 when battery_action='idle'"
            )
        if magnitude < -TOLERANCE_KWH:
            raise ReplayViolation(f"hour {h}: battery_kwh must be non-negative")

        # Battery transition (assume unit efficiency)
        if action == "charge":
            expected_after = energy_before + magnitude
        elif action == "discharge":
            expected_after = energy_before - magnitude
        else:
            expected_after = energy_before
        if abs(expected_after - energy_after) > TOLERANCE_KWH:
            raise ReplayViolation(
                f"hour {h}: battery transition mismatch "
                f"({energy_before} -> {energy_after}; expected {expected_after})"
            )

        # Battery bounds including active reserve
        floor = max(float(battery.minimum_energy_kwh), reserve_map.get(h, 0.0))
        if energy_after < floor - TOLERANCE_KWH:
            raise ReplayViolation(
                f"hour {h}: battery_energy_after_kwh {energy_after} below reserve {floor}"
            )
        if energy_after > battery.capacity_kwh + TOLERANCE_KWH:
            raise ReplayViolation(
                f"hour {h}: battery_energy_after_kwh {energy_after} exceeds capacity"
            )

        # Rate caps
        if action == "charge" and magnitude > battery.max_charge_kwh_per_hour + TOLERANCE_KWH:
            raise ReplayViolation(
                f"hour {h}: charge magnitude exceeds max_charge_kwh_per_hour"
            )
        if action == "discharge" and magnitude > battery.max_discharge_kwh_per_hour + TOLERANCE_KWH:
            raise ReplayViolation(
                f"hour {h}: discharge magnitude exceeds max_discharge_kwh_per_hour"
            )

        # Directive windows
        if action == "charge" and h in no_charge_hours and magnitude > TOLERANCE_KWH:
            raise ReplayViolation(
                f"hour {h}: charging is forbidden by no_charge_window"
            )
        if action == "discharge" and h in no_discharge_hours and magnitude > TOLERANCE_KWH:
            raise ReplayViolation(
                f"hour {h}: discharging is forbidden by no_discharge_window"
            )

        # Solar usage
        if solar_used > effective_solar[h] + TOLERANCE_KWH:
            raise ReplayViolation(
                f"hour {h}: solar_used_kwh {solar_used} exceeds effective solar "
                f"{effective_solar[h]}"
            )

        # Grid cap
        if h in max_grid_map and grid > max_grid_map[h] + TOLERANCE_KWH:
            raise ReplayViolation(
                f"hour {h}: grid_kwh {grid} exceeds max_grid_window cap {max_grid_map[h]}"
            )

        # Energy balance
        charge_amount = magnitude if action == "charge" else 0.0
        discharge_amount = magnitude if action == "discharge" else 0.0
        lhs = grid + solar_used + discharge_amount
        rhs = float(hour_entry.demand_kwh) + charge_amount
        if abs(lhs - rhs) > TOLERANCE_KWH:
            raise ReplayViolation(
                f"hour {h}: energy balance violated "
                f"(grid+solar+discharge={lhs}, demand+charge={rhs})"
            )

        total_grid += grid
        total_cost += grid * float(hour_entry.tariff_bdt_per_kwh)
        peak_grid = max(peak_grid, grid)
        energy_before = energy_after

    if abs(energy_before - battery.initial_energy_kwh) > TOLERANCE_KWH:
        raise ReplayViolation(
            "end-of-day battery neutrality violated: "
            f"final energy {energy_before} != initial {battery.initial_energy_kwh}"
        )

    return ReplayTotals(
        total_grid_kwh=round(total_grid, 6),
        total_cost_bdt=round(total_cost, 6),
        peak_grid_kwh=round(peak_grid, 6),
    )


def expected_totals(plan: list[HourlyPlanEntry], hours: list[HourEntry]) -> ReplayTotals:
    """Recompute totals from a plan without checking constraints."""
    by_hour = {entry.hour: entry for entry in plan}
    total_grid = 0.0
    total_cost = 0.0
    peak_grid = 0.0
    for hour_entry in hours:
        entry = by_hour[hour_entry.hour]
        grid = float(entry.grid_kwh)
        total_grid += grid
        total_cost += grid * float(hour_entry.tariff_bdt_per_kwh)
        peak_grid = max(peak_grid, grid)
    return ReplayTotals(
        total_grid_kwh=round(total_grid, 6),
        total_cost_bdt=round(total_cost, 6),
        peak_grid_kwh=round(peak_grid, 6),
    )
