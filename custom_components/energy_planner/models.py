from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

PlannerState = Literal["ok", "warning", "error", "insufficient_data"]


@dataclass(frozen=True)
class TimeWindow:
    start: str
    end: str


@dataclass(frozen=True)
class ForecastSlot:
    start: datetime
    solar_kwh: float
    consumption_kwh: float


@dataclass(frozen=True)
class SolarForecastPoint:
    start: datetime
    solar_kwh: float
    period_minutes: int | None = None


@dataclass(frozen=True)
class SocForecastPoint:
    timestamp: datetime
    soc_percent: float
    battery_kwh: float
    solar_kwh: float
    consumption_kwh: float
    grid_charge_kwh: float = 0.0
    grid_import_kwh: float = 0.0
    unused_surplus_kwh: float = 0.0
    is_nt: bool = False
    is_charge_window: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "soc_percent": self.soc_percent,
            "battery_kwh": self.battery_kwh,
            "solar_kwh": self.solar_kwh,
            "consumption_kwh": self.consumption_kwh,
            "grid_charge_kwh": self.grid_charge_kwh,
            "grid_import_kwh": self.grid_import_kwh,
            "unused_surplus_kwh": self.unused_surplus_kwh,
            "is_nt": self.is_nt,
            "is_charge_window": self.is_charge_window,
        }


@dataclass(frozen=True)
class PlannerInput:
    now: datetime
    battery_soc: float
    battery_capacity_kwh: float
    battery_min_soc: float
    slots: list[ForecastSlot]
    nt_windows: list[TimeWindow]
    charge_window: TimeWindow
    interval_minutes: int = 5
    grid_charge_max_kw: float = 5.5
    grid_charge_efficiency: float = 0.92
    soc_reserve_percent: float = 1
    soc_eps_kwh: float = 0.02
    sun_start_required_minutes: int = 30
    forecast_horizon_hours: int = 36


@dataclass
class PlannerResult:
    state: PlannerState
    updated: datetime
    plan: dict[str, Any] = field(default_factory=dict)
    forecast: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)
