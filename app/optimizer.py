"""Deterministic LP optimizer for Section 09 of the problem statement.

Decision variables (per hour h in 0..23):
    g[h]  grid import   kWh  >= 0
    c[h]  battery charge kWh  >= 0
    d[h]  battery discharge kWh  >= 0

Objective: minimize sum_h g[h] * tariff[h]  (BDT).

Constraints:
    1. Energy balance per hour
       g[h] + solar_used[h] + d[h] == demand[h] + c[h]
       where solar_used[h] <= effective_solar[h].
    2. Battery transition
       E_after[h] == E_before[h] + eta_in*c[h] - d[h]/eta_out
    3. Battery bounds  min_energy_kwh <= E_after[h] <= capacity_kwh
    4. Rate caps  c[h] <= max_charge_kwh_per_hour, d[h] <= max_discharge_kwh_per_hour
    5. Directive windows (no_charge, no_discharge, max_grid_window, min_reserve)
    6. End-of-day neutrality  E_after[23] == initial_energy_kwh

Effective solar: solar_kwh[h] * factor for hours covered by solar_reduction.
Solar use is an LP variable bounded by effective availability; curtailment is
allowed by the challenge contract.
"""

from __future__ import annotations

from dataclasses import dataclass

from scipy.optimize import linprog

from app.schemas import (
    Battery,
    DirectiveInterpretation,
    HourEntry,
    HourlyPlanEntry,
)


class OptimizationError(Exception):
    """Raised when the LP is infeasible or fails to converge."""


@dataclass(frozen=True)
class OptimizationResult:
    plan: list[HourlyPlanEntry]
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float


def _effective_solar(
    hours: list[HourEntry], interpretations: list[DirectiveInterpretation]
) -> list[float]:
    factors: dict[int, float] = {h.hour: 1.0 for h in hours}
    for entry in interpretations:
        if entry.directive_type != "solar_reduction" or not entry.applies:
            continue
        adj = entry.structured_adjustment or {}
        factor = float(adj.get("factor", 1.0))
        for hour in adj.get("hours", []):
            h = int(hour)
            factors[h] = min(factors.get(h, 1.0), factor)
    return [
        round(float(h.solar_kwh) * factors.get(h.hour, 1.0), 9)
        for h in hours
    ]


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


def _reserve_floors(
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


def _max_grid_caps(
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
            out[h] = cap if h not in out else min(out[h], cap)
    return out


def _grid_from_balance(
    demand: float,
    solar_used: float,
    charge: float,
    discharge: float,
) -> float:
    return demand + charge - solar_used - discharge


def optimize_schedule(
    hours: list[HourEntry],
    battery: Battery,
    interpretations: list[DirectiveInterpretation],
) -> OptimizationResult:
    """Solve the 24-period LP and return a fully-built HourlyPlanEntry list."""
    if len(hours) != 24:
        raise OptimizationError("optimize_schedule requires exactly 24 hours")

    tariffs = [float(h.tariff_bdt_per_kwh) for h in hours]
    demand = [float(h.demand_kwh) for h in hours]
    eff_solar = _effective_solar(hours, interpretations)
    no_charge_hours = _directive_hours(interpretations, "no_charge_window")
    no_discharge_hours = _directive_hours(interpretations, "no_discharge_window")
    reserve_floors = _reserve_floors(interpretations)
    max_grid_caps = _max_grid_caps(interpretations)

    eta_in = 1.0
    eta_out = 1.0

    cap = float(battery.capacity_kwh)
    floor = float(battery.minimum_energy_kwh)
    e0 = float(battery.initial_energy_kwh)
    max_c = float(battery.max_charge_kwh_per_hour)
    max_d = float(battery.max_discharge_kwh_per_hour)

    # Variable layout: [g0..g23, c0..c23, d0..d23, s0..s23] = 96 variables
    # g: grid import
    # c: battery charge
    # d: battery discharge
    # s: solar_used (slack for the greedy solar allocation, bounded [0, eff])
    n = 96

    # Objective: minimize sum_h g[h] * tariff[h] (slacks have zero cost)
    c_obj = [0.0] * n
    for h in range(24):
        c_obj[h] = tariffs[h]

    bounds: list[tuple[float, float | None]] = []
    for h in range(24):
        ub = max_grid_caps.get(h)
        bounds.append((0.0, ub))  # grid
    for h in range(24):
        ub = 0.0 if h in no_charge_hours else max_c
        bounds.append((0.0, ub))  # charge
    for h in range(24):
        ub = 0.0 if h in no_discharge_hours else max_d
        bounds.append((0.0, ub))  # discharge
    for h in range(24):
        bounds.append((0.0, eff_solar[h]))  # solar_used slack

    A_eq: list[list[float]] = []
    b_eq: list[float] = []

    # Equality 1: end-of-day neutrality  E_after[23] == e0
    # E_after[h] = e0 + eta_in * sum_{k<=h} c[k] - (1/eta_out) * sum_{k<=h} d[k]
    # For h=23:  eta_in * sum c - (1/eta_out) * sum d == 0
    row = [0.0] * n
    for h in range(24):
        row[24 + h] = eta_in
        row[48 + h] = -1.0 / eta_out
    A_eq.append(row)
    b_eq.append(0.0)

    # Equality 2..25: per-hour energy balance
    #   g[h] + s[h] + d[h] == demand[h] + c[h]
    for h in range(24):
        row = [0.0] * n
        row[h] = 1.0          # g
        row[24 + h] = -1.0    # c
        row[48 + h] = 1.0     # d
        row[72 + h] = 1.0     # s
        A_eq.append(row)
        b_eq.append(demand[h])

    # Inequalities: per-hour battery bounds
    A_ub: list[list[float]] = []
    b_ub: list[float] = []

    for h in range(24):
        # E_after[h] <= cap
        row = [0.0] * n
        for k in range(h + 1):
            row[24 + k] = eta_in
            row[48 + k] = -1.0 / eta_out
        A_ub.append(row)
        b_ub.append(cap - e0)

        # -E_after[h] <= -active_floor[h]
        active_floor = max(floor, reserve_floors.get(h, floor))
        row = [0.0] * n
        for k in range(h + 1):
            row[24 + k] = -eta_in
            row[48 + k] = 1.0 / eta_out
        A_ub.append(row)
        b_ub.append(e0 - active_floor)

    result = linprog(
        c=c_obj,
        A_ub=A_ub,
        b_ub=b_ub,
        A_eq=A_eq,
        b_eq=b_eq,
        bounds=bounds,
        method="highs",
    )

    if not result.success:
        raise OptimizationError(f"LP failed: {result.message}")

    x = result.x

    grid_vals = [max(0.0, float(x[h])) for h in range(24)]
    charge_vals = [max(0.0, float(x[24 + h])) for h in range(24)]
    discharge_vals = [max(0.0, float(x[48 + h])) for h in range(24)]
    solar_vals = [max(0.0, float(x[72 + h])) for h in range(24)]

    # Build plan with battery_energy_after_kwh derived from cummulative state
    plan: list[HourlyPlanEntry] = []
    energy = e0
    total_grid = 0.0
    total_cost = 0.0
    peak_grid = 0.0

    for h in range(24):
        net_battery = round(charge_vals[h] - discharge_vals[h], 6)
        c_h = max(0.0, net_battery)
        d_h = max(0.0, -net_battery)
        s_h = round(solar_vals[h], 6)
        g_h = round(_grid_from_balance(demand[h], s_h, c_h, d_h), 6)
        if g_h < 0:
            # Solver introduced rounding; clamp solar_used so grid is >= 0
            s_h = round(min(s_h, demand[h] + c_h - d_h), 6)
            g_h = round(_grid_from_balance(demand[h], s_h, c_h, d_h), 6)

        if c_h > TOLERANCE_KWH:
            action = "charge"
            magnitude = c_h
        elif d_h > TOLERANCE_KWH:
            action = "discharge"
            magnitude = d_h
        else:
            action = "idle"
            magnitude = 0.0

        if action == "charge":
            energy_after = energy + eta_in * c_h
        elif action == "discharge":
            energy_after = energy - d_h / eta_out
        else:
            energy_after = energy

        # Clamp to within bounds to keep the plan honest
        energy_after = min(max(energy_after, floor), cap)
        energy = energy_after

        plan.append(
            HourlyPlanEntry(
                hour=h,
                grid_kwh=round(g_h, 6),
                solar_used_kwh=round(s_h, 6),
                battery_action=action,
                battery_kwh=round(magnitude, 6),
                battery_energy_after_kwh=round(energy_after, 6),
            )
        )

        total_grid += g_h
        total_cost += g_h * tariffs[h]
        peak_grid = max(peak_grid, g_h)

    return OptimizationResult(
        plan=plan,
        total_grid_kwh=round(total_grid, 6),
        total_cost_bdt=round(total_cost, 6),
        peak_grid_kwh=round(peak_grid, 6),
    )


TOLERANCE_KWH: float = 0.01
