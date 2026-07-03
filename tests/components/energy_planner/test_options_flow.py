from __future__ import annotations

import pytest

from custom_components.energy_planner.const import (
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
)
from custom_components.energy_planner.options import (
    OptionsValidationError,
    normalize_options,
    parse_window,
    parse_windows,
    serialize_window,
    serialize_windows,
)


def _options(**overrides):
    values = {
        CONF_INTERVAL_MINUTES: 5,
        CONF_HISTORY_CORRECTION_PERCENT: 5,
        CONF_MIN_BASELINE_KWH_PER_HOUR: 0.2,
        CONF_GRID_CHARGE_MAX_KW: 5.5,
        CONF_GRID_CHARGE_EFFICIENCY: 0.92,
        CONF_SOC_RESERVE_PERCENT: 1,
        CONF_SOC_EPS_KWH: 0.02,
        CONF_NT_WINDOWS: "17:00-19:00,22:00-04:00",
        CONF_CHARGE_WINDOW: "22:00-04:00",
        CONF_SUN_START_REQUIRED_MINUTES: 30,
        CONF_FORECAST_HORIZON_HOURS: 36,
    }
    values.update(overrides)
    return values


def test_parse_windows_accepts_across_midnight_window():
    assert parse_window("22:00-04:00") == {"start": "22:00", "end": "04:00"}
    assert parse_windows("17:00-19:00,22:00-04:00") == [
        {"start": "17:00", "end": "19:00"},
        {"start": "22:00", "end": "04:00"},
    ]


def test_serialize_windows_matches_options_ui_format():
    windows = [
        {"start": "17:00", "end": "19:00"},
        {"start": "22:00", "end": "04:00"},
    ]

    assert serialize_window(windows[0]) == "17:00-19:00"
    assert serialize_windows(windows) == "17:00-19:00,22:00-04:00"


def test_normalize_options_converts_ui_values_to_typed_options():
    normalized = normalize_options(_options())

    assert normalized[CONF_INTERVAL_MINUTES] == 5
    assert normalized[CONF_HISTORY_CORRECTION_PERCENT] == 5
    assert normalized[CONF_FORECAST_HORIZON_HOURS] == 36
    assert normalized[CONF_NT_WINDOWS][1] == {"start": "22:00", "end": "04:00"}
    assert normalized[CONF_CHARGE_WINDOW] == {"start": "22:00", "end": "04:00"}


@pytest.mark.parametrize(
    ("key", "value"),
    [
        (CONF_INTERVAL_MINUTES, 7),
        (CONF_FORECAST_HORIZON_HOURS, 23),
        (CONF_HISTORY_CORRECTION_PERCENT, -100),
        (CONF_GRID_CHARGE_EFFICIENCY, 1.1),
        (CONF_NT_WINDOWS, "invalid"),
        (CONF_CHARGE_WINDOW, "25:00-26:00"),
    ],
)
def test_normalize_options_rejects_invalid_values(key, value):
    with pytest.raises(OptionsValidationError):
        normalize_options(_options(**{key: value}))
