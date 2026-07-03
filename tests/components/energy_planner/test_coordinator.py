from __future__ import annotations

from datetime import datetime

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.energy_planner.const import (
    CONF_SOLCAST_ADDITIONAL_ENTITIES,
    CONF_SOLCAST_TODAY_ENTITY,
    CONF_SOLCAST_TOMORROW_ENTITY,
    DOMAIN,
)
from custom_components.energy_planner.coordinator import (
    _consumption_from_hourly_profile,
    _solcast_entity_ids,
)
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


def test_solcast_entity_ids_autodetect_standard_daily_forecasts_from_today(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_SOLCAST_TODAY_ENTITY: "sensor.solcast_pv_forecast_forecast_today",
        },
    )

    for entity_id in (
        "sensor.solcast_pv_forecast_forecast_today",
        "sensor.solcast_pv_forecast_forecast_tomorrow",
        "sensor.solcast_pv_forecast_forecast_day_3",
        "sensor.solcast_pv_forecast_forecast_day_4",
    ):
        hass.states.async_set(entity_id, "0")

    assert _solcast_entity_ids(hass, entry) == [
        "sensor.solcast_pv_forecast_forecast_today",
        "sensor.solcast_pv_forecast_forecast_tomorrow",
        "sensor.solcast_pv_forecast_forecast_day_3",
        "sensor.solcast_pv_forecast_forecast_day_4",
    ]


def test_solcast_entity_ids_do_not_duplicate_explicit_forecast_days(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_SOLCAST_TODAY_ENTITY: "sensor.solcast_pv_forecast_forecast_today",
            CONF_SOLCAST_TOMORROW_ENTITY: "sensor.custom_solcast_tomorrow",
            CONF_SOLCAST_ADDITIONAL_ENTITIES: [
                "sensor.custom_solcast_day_3",
                "sensor.solcast_pv_forecast_forecast_day_4",
            ],
        },
    )

    for entity_id in (
        "sensor.solcast_pv_forecast_forecast_today",
        "sensor.solcast_pv_forecast_forecast_tomorrow",
        "sensor.solcast_pv_forecast_forecast_day_3",
        "sensor.solcast_pv_forecast_forecast_day_4",
    ):
        hass.states.async_set(entity_id, "0")

    assert _solcast_entity_ids(hass, entry) == [
        "sensor.solcast_pv_forecast_forecast_today",
        "sensor.custom_solcast_tomorrow",
        "sensor.custom_solcast_day_3",
        "sensor.solcast_pv_forecast_forecast_day_4",
    ]


def test_consumption_from_hourly_profile_uses_target_hour_and_correction():
    assert (
        _consumption_from_hourly_profile(
            hourly_profile={11: 2.0},
            target=datetime(2026, 7, 3, 11, 0),
            min_baseline_kwh_per_hour=0.2,
            history_correction_percent=3,
        )
        == 2.06
    )
    assert (
        _consumption_from_hourly_profile(
            hourly_profile={10: 5.0},
            target=datetime(2026, 7, 3, 11, 0),
            min_baseline_kwh_per_hour=0.2,
            history_correction_percent=3,
        )
        == 0.2
    )
