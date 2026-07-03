from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from custom_components.energy_planner.models import (
    PlannerInput,
    SolarForecastPoint,
    TimeWindow,
)
from custom_components.energy_planner.planner import (
    calculate_plan,
    generate_forecast_slots,
)

FIXTURE_PATH = (
    Path(__file__).parents[2] / "fixtures" / "legacy_active_flow_sunny_charge.json"
)


def _load_fixture():
    return json.loads(FIXTURE_PATH.read_text())


def _time_window(value: dict[str, str]) -> TimeWindow:
    return TimeWindow(start=value["start"], end=value["end"])


def _solar_forecast_points(now: datetime, hourly_profile):
    points = []
    for hour_offset in range(24):
        timestamp = now + timedelta(hours=hour_offset)
        solar_kwh = next(
            item["solar_kwh"]
            for item in hourly_profile
            if item["hour"] == timestamp.hour
        )
        points.append(
            SolarForecastPoint(
                start=timestamp,
                solar_kwh=solar_kwh,
                period_minutes=60,
            )
        )
    return points


def _planner_input_from_fixture(fixture) -> PlannerInput:
    planner_input = fixture["planner_input"]
    ha = fixture["home_assistant"]
    now = datetime.fromisoformat(planner_input["now"])
    slots = generate_forecast_slots(
        now=now,
        horizon_hours=planner_input["forecast_horizon_hours"],
        interval_minutes=planner_input["interval_minutes"],
        solar_forecast=_solar_forecast_points(
            now,
            planner_input["solar_hourly_kwh"],
        ),
        consumption_kwh_per_hour=planner_input["consumption_kwh_per_hour"],
    )

    return PlannerInput(
        now=now,
        battery_soc=ha["battery_soc_percent"],
        battery_capacity_kwh=ha["battery_capacity_kwh"],
        battery_min_soc=ha["legacy_effective_min_soc_percent"],
        slots=slots,
        nt_windows=[_time_window(window) for window in planner_input["nt_windows"]],
        charge_window=_time_window(planner_input["charge_window"]),
        interval_minutes=planner_input["interval_minutes"],
        grid_charge_max_kw=planner_input["grid_charge_max_kw"],
        grid_charge_efficiency=planner_input["grid_charge_efficiency"],
        soc_reserve_percent=planner_input["soc_reserve_percent"],
        soc_eps_kwh=planner_input["soc_eps_kwh"],
        sun_start_required_minutes=planner_input["sun_start_required_minutes"],
        forecast_horizon_hours=planner_input["forecast_horizon_hours"],
    )


def test_planner_matches_sanitized_active_nodered_flow_outputs():
    fixture = _load_fixture()
    result = calculate_plan(_planner_input_from_fixture(fixture))

    assert result.state == "ok"
    for key, expected in fixture["expected_active_flow"].items():
        actual = result.plan[key]
        if isinstance(expected, int | float):
            assert actual == pytest.approx(expected, abs=0.05), key
        else:
            assert actual == expected, key


def test_nodered_export_is_not_used_by_parity_tests():
    assert "nodered_export.json" not in FIXTURE_PATH.read_text()
