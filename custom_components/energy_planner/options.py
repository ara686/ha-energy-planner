from __future__ import annotations

import re
from typing import Any

from .const import (
    CONF_CHARGE_WINDOW,
    CONF_CHARGE_WINDOW_END,
    CONF_CHARGE_WINDOW_START,
    CONF_FORECAST_HORIZON_HOURS,
    CONF_GRID_CHARGE_EFFICIENCY,
    CONF_GRID_CHARGE_MAX_KW,
    CONF_HISTORY_CORRECTION_PERCENT,
    CONF_HISTORY_LEARNING_DAYS,
    CONF_INTERVAL_MINUTES,
    CONF_MIN_BASELINE_KWH_PER_HOUR,
    CONF_NT_WINDOW_1_END,
    CONF_NT_WINDOW_1_START,
    CONF_NT_WINDOW_2_END,
    CONF_NT_WINDOW_2_START,
    CONF_NT_WINDOWS,
    CONF_SOC_EPS_KWH,
    CONF_SOC_RESERVE_PERCENT,
    CONF_SUN_START_REQUIRED_MINUTES,
    CONF_UPDATE_INTERVAL_MINUTES,
    DEFAULT_CHARGE_WINDOW,
    DEFAULT_FORECAST_HORIZON_HOURS,
    DEFAULT_GRID_CHARGE_EFFICIENCY,
    DEFAULT_GRID_CHARGE_MAX_KW,
    DEFAULT_HISTORY_CORRECTION_PERCENT,
    DEFAULT_HISTORY_LEARNING_DAYS,
    DEFAULT_INTERVAL_MINUTES,
    DEFAULT_MIN_BASELINE_KWH_PER_HOUR,
    DEFAULT_NT_WINDOWS,
    DEFAULT_SOC_EPS_KWH,
    DEFAULT_SOC_RESERVE_PERCENT,
    DEFAULT_SUN_START_REQUIRED_MINUTES,
    DEFAULT_UPDATE_INTERVAL_MINUTES,
)

WINDOW_RE = re.compile(r"^(?P<start>\d{2}:\d{2})-(?P<end>\d{2}:\d{2})$")


class OptionsValidationError(ValueError):
    """Raised when user options cannot be normalized."""

    def __init__(self, error_key: str = "invalid_options") -> None:
        self.error_key = error_key
        super().__init__(error_key)


def default_options() -> dict[str, Any]:
    return {
        CONF_UPDATE_INTERVAL_MINUTES: DEFAULT_UPDATE_INTERVAL_MINUTES,
        CONF_HISTORY_LEARNING_DAYS: DEFAULT_HISTORY_LEARNING_DAYS,
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
    update_interval_minutes = _int_value(values, CONF_UPDATE_INTERVAL_MINUTES)
    if update_interval_minutes <= 0:
        raise OptionsValidationError("update_interval_minutes")

    history_learning_days = _int_value(values, CONF_HISTORY_LEARNING_DAYS)
    if history_learning_days <= 0:
        raise OptionsValidationError("history_learning_days")

    interval_minutes = _int_value(values, CONF_INTERVAL_MINUTES)
    if interval_minutes <= 0 or 60 % interval_minutes != 0:
        raise OptionsValidationError("interval_minutes")

    horizon_hours = _int_value(values, CONF_FORECAST_HORIZON_HOURS)
    if horizon_hours < 24:
        raise OptionsValidationError("forecast_horizon_hours")

    min_baseline = _float_value(values, CONF_MIN_BASELINE_KWH_PER_HOUR)
    history_correction_percent = _float_value(
        values,
        CONF_HISTORY_CORRECTION_PERCENT,
        default=DEFAULT_HISTORY_CORRECTION_PERCENT,
    )
    grid_charge_max_kw = _float_value(values, CONF_GRID_CHARGE_MAX_KW)
    grid_charge_efficiency = _float_value(values, CONF_GRID_CHARGE_EFFICIENCY)
    soc_reserve_percent = _float_value(values, CONF_SOC_RESERVE_PERCENT)
    soc_eps_kwh = _float_value(values, CONF_SOC_EPS_KWH)
    sun_start_required_minutes = _int_value(values, CONF_SUN_START_REQUIRED_MINUTES)

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
        CONF_UPDATE_INTERVAL_MINUTES: update_interval_minutes,
        CONF_HISTORY_LEARNING_DAYS: history_learning_days,
        CONF_INTERVAL_MINUTES: interval_minutes,
        CONF_HISTORY_CORRECTION_PERCENT: history_correction_percent,
        CONF_MIN_BASELINE_KWH_PER_HOUR: min_baseline,
        CONF_GRID_CHARGE_MAX_KW: grid_charge_max_kw,
        CONF_GRID_CHARGE_EFFICIENCY: grid_charge_efficiency,
        CONF_SOC_RESERVE_PERCENT: soc_reserve_percent,
        CONF_SOC_EPS_KWH: soc_eps_kwh,
        CONF_NT_WINDOWS: _nt_windows_from_values(values),
        CONF_CHARGE_WINDOW: _charge_window_from_values(values),
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
    if start == end:
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


def _nt_windows_from_values(values: dict[str, Any]) -> list[dict[str, str]]:
    if {
        CONF_NT_WINDOW_1_START,
        CONF_NT_WINDOW_1_END,
        CONF_NT_WINDOW_2_START,
        CONF_NT_WINDOW_2_END,
    }.issubset(values):
        return [
            parse_window(
                {
                    "start": values.get(CONF_NT_WINDOW_1_START),
                    "end": values.get(CONF_NT_WINDOW_1_END),
                }
            ),
            parse_window(
                {
                    "start": values.get(CONF_NT_WINDOW_2_START),
                    "end": values.get(CONF_NT_WINDOW_2_END),
                }
            ),
        ]
    if CONF_NT_WINDOWS in values:
        return parse_windows(values[CONF_NT_WINDOWS])
    raise OptionsValidationError("windows")


def _charge_window_from_values(values: dict[str, Any]) -> dict[str, str]:
    if {CONF_CHARGE_WINDOW_START, CONF_CHARGE_WINDOW_END}.issubset(values):
        return parse_window(
            {
                "start": values.get(CONF_CHARGE_WINDOW_START),
                "end": values.get(CONF_CHARGE_WINDOW_END),
            }
        )
    if CONF_CHARGE_WINDOW in values:
        return parse_window(values[CONF_CHARGE_WINDOW])
    raise OptionsValidationError("window")


def _int_value(
    values: dict[str, Any],
    key: str,
    *,
    default: int | None = None,
) -> int:
    try:
        raw_value = values[key]
    except KeyError as err:
        if default is None:
            raise OptionsValidationError(key) from err
        raw_value = default
    try:
        return int(raw_value)
    except (TypeError, ValueError) as err:
        raise OptionsValidationError(key) from err


def _float_value(
    values: dict[str, Any],
    key: str,
    *,
    default: float | None = None,
) -> float:
    try:
        raw_value = values[key]
    except KeyError as err:
        if default is None:
            raise OptionsValidationError(key) from err
        raw_value = default
    try:
        return float(raw_value)
    except (TypeError, ValueError) as err:
        raise OptionsValidationError(key) from err


def _valid_hhmm(value: str) -> bool:
    if not re.match(r"^\d{2}:\d{2}$", value):
        return False
    hour, minute = value.split(":", 1)
    return 0 <= int(hour) <= 23 and 0 <= int(minute) <= 59
