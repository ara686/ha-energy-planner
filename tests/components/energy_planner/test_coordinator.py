from __future__ import annotations

from datetime import datetime

from custom_components.energy_planner.sources import (
    parse_float,
    parse_solcast_attributes,
)


def test_parse_float_accepts_home_assistant_state_strings():
    assert parse_float("12.5") == 12.5
    assert parse_float("12,5") == 12.5
    assert parse_float("unknown") is None
    assert parse_float("unavailable") is None
    assert parse_float("not-a-number") is None


def test_parse_solcast_detailed_forecast_attributes():
    points = parse_solcast_attributes(
        {
            "detailedForecast": [
                {
                    "period_start": "2026-07-03T10:00:00+02:00",
                    "pv_estimate": 1.25,
                    "period_minutes": 30,
                },
                {
                    "period_start": "2026-07-03T10:30:00+02:00",
                    "pv_estimate": "1,5",
                    "period_minutes": "30",
                },
            ]
        }
    )

    assert len(points) == 2
    assert points[0].start == datetime.fromisoformat("2026-07-03T10:00:00+02:00")
    assert points[0].solar_kwh == 0.625
    assert points[0].period_minutes == 30
    assert points[1].solar_kwh == 0.75


def test_parse_solcast_detailed_forecast_infers_period_length_for_power_values():
    points = parse_solcast_attributes(
        {
            "detailedForecast": [
                {
                    "period_start": "2026-07-03T10:00:00+02:00",
                    "pv_estimate": 1.0,
                },
                {
                    "period_start": "2026-07-03T10:30:00+02:00",
                    "pv_estimate": 2.0,
                },
            ]
        }
    )

    assert [point.period_minutes for point in points] == [30, 30]
    assert [point.solar_kwh for point in points] == [0.5, 1.0]


def test_parse_solcast_explicit_energy_values_remain_kwh():
    points = parse_solcast_attributes(
        {
            "detailedForecast": [
                {
                    "period_start": "2026-07-03T10:00:00+02:00",
                    "solar_kwh": 1.25,
                    "period_minutes": 30,
                },
            ]
        }
    )

    assert points[0].solar_kwh == 1.25
    assert points[0].period_minutes == 30


def test_parse_solcast_attributes_supports_wh_fallback_and_skips_invalid_rows():
    points = parse_solcast_attributes(
        {
            "forecast": [
                {
                    "period_start": "bad-date",
                    "pv_estimate": 1.0,
                },
                {
                    "period_start": "2026-07-03T11:00:00Z",
                    "pv_estimate_wh": 750,
                },
            ]
        }
    )

    assert len(points) == 1
    assert points[0].start == datetime.fromisoformat("2026-07-03T11:00:00+00:00")
    assert points[0].solar_kwh == 0.75
