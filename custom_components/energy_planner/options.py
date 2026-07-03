from __future__ import annotations

import re
from typing import Any

from .const import (
    CONF_CHARGE_WINDOW,
    CONF_FORECAST_HORIZON_HOURS,
    CONF_GRID_CHARGE_EFFICIENCY,
    CONF_GRID_CHARGE_MAX_KW,
    CONF_HISTORY_CORRECTION_PERCENT,
    CONF_INTERVAL_MINUTES,
    CONF_MIN_BASELINE_KWH_PER_HOUR,
    CONF_NT_WINDOWS,
    CONF_SOC_EPS_KWH,
    CONF_SOC_RESERVE_PERCENT,
    CONF_SUN_START_REQUIRED_MINUTES,
    DEFAULT_CHARGE_WINDOW,
    DEFAULT_FORECAST_HORIZON_HOURS,
    DEFAULT_GRID_CHARGE_EFFICIENCY,
    DEFAULT_GRID_CHARGE_MAX_KW,
    DEFAULT_HISTORY_CORRECTION_PERCENT,
    DEFAULT_INTERVAL_MINUTES,
    DEFAULT_MIN_BASELINE_KWH_PER_HOUR,
    DEFAULT_NT_WINDOWS,
    DEFAULT_SOC_EPS_KWH,
    DEFAULT_SOC_RESERVE_PERCENT,
    DEFAULT_SUN_START_REQUIRED_MINUTES,
)

WINDOW_RE = re.compile(r"^(?P<start>\d{2}:\d{2})-(?P<end>\d{2}:\d{2})$")


class OptionsValidationError(ValueError):
    """Raised when user options cannot be normalized."""


def default_options() -> dict[str, Any]:
    return {
        CONF_INTERVAL_MINUTES: DEFAULT_INTERVAL_MINUTES,
        CONF_HISTORY_CORRECTION_PERCENT: DEFAULT_HISTORY_CORRECTION_PERCENT,
        CONF_MIN_BASELINE_KWH_PER_HOUR: DEFAULT_MIN_BASELINE_KWH_PER_HOUR,
        CONF_GRID_CHARGE_MAX_KW: DEFAULT_GRID_CHARGE_MAX_KW,
        CONF_GRID_CHARGE_EFFICIENCY: DEFAULT_GRID_CHARGE_EFFICIENCY,
        CONF_SOC_RESERVE_PERCENT: DEFAULT_SOC_RESERVE_PERCENT,
        CONF_SOC_EPS_KWH: DEFAULT_SOC_EPS_KWH,
        CONF_NT_WINDOWS: DEFAULT_NT_WINDOWS,
        CONF_CHARGE_WINDOW: DEFAULT_CHARGE_WINDOW,
        CONF_SUN_START_REQUIRED_MINUTES: DEFAULT_SUN_START_REQUIRED_MINUTES,
        CONF_FORECAST_HORIZON_HOURS: DEFAULT_FORECAST_HORIZON_HOURS,
    }


def normalize_options(values: dict[str, Any]) -> dict[str, Any]:
    interval_minutes = int(values[CONF_INTERVAL_MINUTES])
    if interval_minutes <= 0 or 60 % interval_minutes != 0:
        raise OptionsValidationError("interval_minutes")

    horizon_hours = int(values[CONF_FORECAST_HORIZON_HOURS])
    if horizon_hours < 24:
        raise OptionsValidationError("forecast_horizon_hours")

    min_baseline = float(values[CONF_MIN_BASELINE_KWH_PER_HOUR])
    history_correction_percent = float(
        values.get(
            CONF_HISTORY_CORRECTION_PERCENT,
            DEFAULT_HISTORY_CORRECTION_PERCENT,
        )
    )
    grid_charge_max_kw = float(values[CONF_GRID_CHARGE_MAX_KW])
    grid_charge_efficiency = float(values[CONF_GRID_CHARGE_EFFICIENCY])
    soc_reserve_percent = float(values[CONF_SOC_RESERVE_PERCENT])
    soc_eps_kwh = float(values[CONF_SOC_EPS_KWH])
    sun_start_required_minutes = int(values[CONF_SUN_START_REQUIRED_MINUTES])

    if min_baseline < 0:
        raise OptionsValidationError("min_baseline_kwh_per_hour")
    if history_correction_percent <= -100 or history_correction_percent > 500:
        raise OptionsValidationError("history_correction_percent")
    if grid_charge_max_kw < 0:
        raise OptionsValidationError("grid_charge_max_kw")
    if not 0 < grid_charge_efficiency <= 1:
        raise OptionsValidationError("grid_charge_efficiency")
    if not 0 <= soc_reserve_percent <= 100:
        raise OptionsValidationError("soc_reserve_percent")
    if soc_eps_kwh < 0:
        raise OptionsValidationError("soc_eps_kwh")
    if sun_start_required_minutes <= 0:
        raise OptionsValidationError("sun_start_required_minutes")

    return {
        CONF_INTERVAL_MINUTES: interval_minutes,
        CONF_HISTORY_CORRECTION_PERCENT: history_correction_percent,
        CONF_MIN_BASELINE_KWH_PER_HOUR: min_baseline,
        CONF_GRID_CHARGE_MAX_KW: grid_charge_max_kw,
        CONF_GRID_CHARGE_EFFICIENCY: grid_charge_efficiency,
        CONF_SOC_RESERVE_PERCENT: soc_reserve_percent,
        CONF_SOC_EPS_KWH: soc_eps_kwh,
        CONF_NT_WINDOWS: parse_windows(values[CONF_NT_WINDOWS]),
        CONF_CHARGE_WINDOW: parse_window(values[CONF_CHARGE_WINDOW]),
        CONF_SUN_START_REQUIRED_MINUTES: sun_start_required_minutes,
        CONF_FORECAST_HORIZON_HOURS: horizon_hours,
    }


def parse_windows(value: Any) -> list[dict[str, str]]:
    if isinstance(value, list):
        windows = [parse_window(item) for item in value]
    elif isinstance(value, str):
        windows = [
            parse_window(item.strip()) for item in value.split(",") if item.strip()
        ]
    else:
        raise OptionsValidationError("windows")

    if not windows:
        raise OptionsValidationError("windows")
    return windows


def parse_window(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        start = str(value.get("start", ""))
        end = str(value.get("end", ""))
    elif isinstance(value, str):
        match = WINDOW_RE.match(value.strip())
        if not match:
            raise OptionsValidationError("window")
        start = match.group("start")
        end = match.group("end")
    else:
        raise OptionsValidationError("window")

    if not _valid_hhmm(start) or not _valid_hhmm(end):
        raise OptionsValidationError("window")
    return {"start": start, "end": end}


def serialize_windows(value: list[dict[str, str]]) -> str:
    return ",".join(serialize_window(window) for window in value)


def serialize_window(value: dict[str, str]) -> str:
    return f"{value['start']}-{value['end']}"


def merged_options(existing: dict[str, Any]) -> dict[str, Any]:
    options = default_options()
    options.update(existing)
    return options


def _valid_hhmm(value: str) -> bool:
    if not re.match(r"^\d{2}:\d{2}$", value):
        return False
    hour, minute = value.split(":", 1)
    return 0 <= int(hour) <= 23 and 0 <= int(minute) <= 59
