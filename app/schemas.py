from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class HourEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    hour: int = Field(..., ge=0, le=23)
    demand_kwh: float = Field(..., ge=0)
    solar_kwh: float = Field(..., ge=0)
    tariff_bdt_per_kwh: float = Field(..., ge=0)


class Battery(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    capacity_kwh: float = Field(..., gt=0)
    initial_energy_kwh: float = Field(..., ge=0)
    minimum_energy_kwh: float = Field(..., ge=0)
    max_charge_kwh_per_hour: float = Field(..., ge=0)
    max_discharge_kwh_per_hour: float = Field(..., ge=0)

    @model_validator(mode="after")
    def validate_energy_bounds(self) -> "Battery":
        if self.minimum_energy_kwh > self.capacity_kwh:
            raise ValueError("minimum_energy_kwh must not exceed capacity_kwh")
        if self.initial_energy_kwh > self.capacity_kwh:
            raise ValueError("initial_energy_kwh must not exceed capacity_kwh")
        if self.initial_energy_kwh < self.minimum_energy_kwh:
            raise ValueError("initial_energy_kwh must not be below minimum_energy_kwh")
        return self


class OptimizeEnergyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(..., min_length=1)
    operator_notes: list[str] = Field(..., min_length=1, max_length=3)
    hours: list[HourEntry] = Field(..., min_length=24, max_length=24)
    battery: Battery

    @field_validator("scenario_id")
    @classmethod
    def validate_scenario_id(cls, scenario_id: str) -> str:
        if not scenario_id.strip():
            raise ValueError("scenario_id must not be blank")
        return scenario_id

    @field_validator("operator_notes")
    @classmethod
    def validate_notes(cls, notes: list[str]) -> list[str]:
        if any(not note.strip() for note in notes):
            raise ValueError("operator_notes entries must be non-empty strings")
        return notes

    @field_validator("hours")
    @classmethod
    def validate_complete_day(cls, hours: list[HourEntry]) -> list[HourEntry]:
        hour_numbers = [entry.hour for entry in hours]
        if sorted(hour_numbers) != list(range(24)):
            raise ValueError("hours must contain exactly one entry for each hour 0 through 23")
        return sorted(hours, key=lambda entry: entry.hour)


DirectiveType = Literal[
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
]

BatteryAction = Literal["charge", "discharge", "idle"]


class DirectiveInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note_index: int = Field(..., ge=0)
    applies: bool
    directive_type: DirectiveType
    structured_adjustment: dict | None
    explanation: str = Field(..., min_length=1)


class HourlyPlanEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    hour: int = Field(..., ge=0, le=23)
    grid_kwh: float = Field(..., ge=0)
    solar_used_kwh: float = Field(..., ge=0)
    battery_action: BatteryAction
    battery_kwh: float = Field(..., ge=0)
    battery_energy_after_kwh: float = Field(..., ge=0)


class OptimizeEnergyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    scenario_id: str
    directive_interpretation: list[DirectiveInterpretation]
    hourly_plan: list[HourlyPlanEntry] = Field(..., min_length=24, max_length=24)
    total_grid_kwh: float = Field(..., ge=0)
    total_cost_bdt: float = Field(..., ge=0)
    peak_grid_kwh: float = Field(..., ge=0)
    plan_summary: str = Field(..., min_length=1)
