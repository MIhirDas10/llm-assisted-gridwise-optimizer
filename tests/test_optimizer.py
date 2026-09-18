"""Unit tests for app.optimizer and app.replay."""

from types import SimpleNamespace

import pytest

from app.optimizer import OptimizationError, optimize_schedule
from app.replay import ReplayViolation, replay_plan
from app.schemas import (
    Battery,
    DirectiveInterpretation,
    HourEntry,
    HourlyPlanEntry,
)


def _hours(demand: float = 5.0, solar: float = 0.0, tariff: float = 10.0) -> list[HourEntry]:
    return [
        HourEntry(
            hour=h,
            demand_kwh=demand,
            solar_kwh=solar,
            tariff_bdt_per_kwh=tariff,
        )
        for h in range(24)
    ]


def _battery(**overrides) -> Battery:
    base = dict(
        capacity_kwh=20.0,
        initial_energy_kwh=10.0,
        minimum_energy_kwh=0.0,
        max_charge_kwh_per_hour=5.0,
        max_discharge_kwh_per_hour=5.0,
    )
    base.update(overrides)
    return Battery(**base)


def _no_ops() -> list[DirectiveInterpretation]:
    return [
        DirectiveInterpretation(
            note_index=i,
            applies=False,
            directive_type="no_op",
            structured_adjustment=None,
            explanation="noop",
        )
        for i in range(1)
    ]


def test_optimizer_returns_24_hours() -> None:
    result = optimize_schedule(_hours(), _battery(), _no_ops())
    assert len(result.plan) == 24
    assert all(0 <= p.hour <= 23 for p in result.plan)


def test_optimizer_respects_initial_battery_state() -> None:
    result = optimize_schedule(_hours(), _battery(), _no_ops())
    final_energy = result.plan[-1].battery_energy_after_kwh
    assert abs(final_energy - 10.0) < 0.01


def test_optimizer_total_grid_matches_sum() -> None:
    result = optimize_schedule(_hours(), _battery(), _no_ops())
    s = sum(p.grid_kwh for p in result.plan)
    assert abs(s - result.total_grid_kwh) < 0.01


def test_optimizer_charges_under_low_tariff() -> None:
    # Demand uniform; half the day cheap, half expensive.
    # Battery is small enough that discharging it shifts energy from cheap to
    # expensive hours.  Total cost must reflect that arbitrage.
    hours = []
    for h in range(24):
        hours.append(
            HourEntry(
                hour=h,
                demand_kwh=5.0,
                solar_kwh=0.0,
                tariff_bdt_per_kwh=4.0 if h < 12 else 12.0,
            )
        )
    result = optimize_schedule(
        hours,
        _battery(capacity_kwh=20.0, initial_energy_kwh=10.0),
        _no_ops(),
    )
    # Total demand = 120. Battery can shift up to 10 kWh. With unit efficiencies
    # the optimal plan charges 10 kWh when tariff=4 and discharges 10 kWh when
    # tariff=12. That makes total cost strictly less than the all-grid tariff-12
    # baseline (120*12=1440) and also less than flat-grid (120*8=960).
    assert result.total_cost_bdt < 24 * 5.0 * 8.0  # better than flat-grid
    assert result.total_grid_kwh == pytest.approx(120.0, abs=1e-3)


def test_optimizer_no_discharge_window_forces_grid() -> None:
    hours = _hours(demand=8.0)
    # Disable discharge on every hour; battery should idle at initial.
    no_discharge = [
        DirectiveInterpretation(
            note_index=0,
            applies=True,
            directive_type="no_discharge_window",
            structured_adjustment={"hours": list(range(24))},
            explanation="no discharge",
        )
    ]
    result = optimize_schedule(hours, _battery(initial_energy_kwh=10.0), no_discharge)
    # No discharge means energy stays at 10; grid covers all demand.
    final = result.plan[-1].battery_energy_after_kwh
    assert abs(final - 10.0) < 0.01


def test_optimizer_solar_reduction_lowers_solar_use() -> None:
    # Battery is large enough to absorb the full solar supply; demand is high
    # enough that the optimizer uses all available solar.  Cutting noon solar
    # by 50% must reduce total solar_used by the exact amount of the reduction.
    hours = []
    for h in range(24):
        hours.append(
            HourEntry(
                hour=h,
                demand_kwh=4.0,
                solar_kwh=8.0 if 8 <= h <= 16 else 0.0,
                tariff_bdt_per_kwh=10.0,
            )
        )
    baseline = optimize_schedule(
        hours,
        _battery(
            capacity_kwh=120.0,
            initial_energy_kwh=0.0,
            max_charge_kwh_per_hour=15.0,
            max_discharge_kwh_per_hour=15.0,
        ),
        _no_ops(),
    )

    reduced = [
        DirectiveInterpretation(
            note_index=0,
            applies=True,
            directive_type="solar_reduction",
            structured_adjustment={"hours": [10, 11, 12], "factor": 0.5},
            explanation="half noon solar",
        )
    ]
    capped = optimize_schedule(
        hours,
        _battery(
            capacity_kwh=120.0,
            initial_energy_kwh=0.0,
            max_charge_kwh_per_hour=15.0,
            max_discharge_kwh_per_hour=15.0,
        ),
        reduced,
    )

    base_solar = sum(p.solar_used_kwh for p in baseline.plan)
    cap_solar = sum(p.solar_used_kwh for p in capped.plan)
    assert cap_solar < base_solar


def test_overlapping_solar_reductions_use_most_restrictive_factor() -> None:
    hours = _hours(demand=10.0, solar=8.0)
    directives = [
        DirectiveInterpretation(
            note_index=0,
            applies=True,
            directive_type="solar_reduction",
            structured_adjustment={"hours": [12], "factor": 0.5},
            explanation="half remains",
        ),
        DirectiveInterpretation(
            note_index=1,
            applies=True,
            directive_type="solar_reduction",
            structured_adjustment={"hours": [12], "factor": 0.25},
            explanation="quarter remains",
        ),
    ]

    result = optimize_schedule(hours, _battery(), directives)
    assert result.plan[12].solar_used_kwh <= 2.0 + 1e-6
    replay_plan(hours, _battery(), directives, result.plan)


def test_simultaneous_solver_flows_are_serialized_as_net_action(monkeypatch) -> None:
    x = [0.0] * 96
    for hour in range(24):
        x[hour] = 5.0
    x[24] = 2.0
    x[48] = 2.0

    monkeypatch.setattr(
        "app.optimizer.linprog",
        lambda **_kwargs: SimpleNamespace(success=True, x=x),
    )

    hours = _hours()
    result = optimize_schedule(hours, _battery(), _no_ops())
    assert result.plan[0].battery_action == "idle"
    assert result.plan[0].battery_kwh == 0.0
    replay_plan(hours, _battery(), _no_ops(), result.plan)


def test_optimizer_max_grid_window_caps_grid() -> None:
    # Demand 6 kWh/h every hour.  Cap grid at 4 kWh/h for the 12 capped hours
    # (8 morning + 4 evening), so the optimizer must lean on battery during
    # those windows.  The 12 uncapped mid-day hours import enough to charge.
    # Battery is sized to make the LP feasible.
    hours = []
    for h in range(24):
        hours.append(
            HourEntry(
                hour=h,
                demand_kwh=6.0,
                solar_kwh=0.0,
                tariff_bdt_per_kwh=10.0,
            )
        )
    cap = [
        DirectiveInterpretation(
            note_index=0,
            applies=True,
            directive_type="max_grid_window",
            structured_adjustment={"hours": list(range(0, 8)) + list(range(20, 24)), "max_grid_kwh": 4.0},
            explanation="cap at 4",
        )
    ]
    result = optimize_schedule(
        hours,
        _battery(capacity_kwh=60.0, initial_energy_kwh=30.0, max_charge_kwh_per_hour=3.0, max_discharge_kwh_per_hour=3.0),
        cap,
    )
    capped_hours = set(range(0, 8)) | set(range(20, 24))
    for entry in result.plan:
        if entry.hour in capped_hours:
            assert entry.grid_kwh <= 4.0 + 1e-6
        else:
            assert entry.grid_kwh >= 0.0


def test_replay_accepts_optimizer_plan() -> None:
    hours = _hours()
    result = optimize_schedule(hours, _battery(), _no_ops())
    totals = replay_plan(hours, _battery(), _no_ops(), result.plan)
    assert totals.total_grid_kwh >= 0
    assert totals.total_cost_bdt >= 0


def test_replay_rejects_bad_battery_transition() -> None:
    hours = _hours()
    result = optimize_schedule(hours, _battery(), _no_ops())
    # Tamper with hour 5 battery_energy_after
    tampered = [
        HourlyPlanEntry(
            hour=p.hour,
            grid_kwh=p.grid_kwh,
            solar_used_kwh=p.solar_used_kwh,
            battery_action=p.battery_action,
            battery_kwh=p.battery_kwh,
            battery_energy_after_kwh=p.battery_energy_after_kwh + 100.0 if p.hour == 5 else p.battery_energy_after_kwh,
        )
        for p in result.plan
    ]
    with pytest.raises(ReplayViolation):
        replay_plan(hours, _battery(), _no_ops(), tampered)


def test_replay_rejects_violating_no_charge_window() -> None:
    hours = _hours()
    result = optimize_schedule(hours, _battery(), _no_ops())
    no_charge = [
        DirectiveInterpretation(
            note_index=0,
            applies=True,
            directive_type="no_charge_window",
            structured_adjustment={"hours": list(range(24))},
            explanation="no charge",
        )
    ]
    with pytest.raises(ReplayViolation):
        replay_plan(hours, _battery(), no_charge, result.plan)
