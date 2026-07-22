from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.energy_planner.const import (
    CONF_BATTERY_CAPACITY_ENTITY,
    CONF_BATTERY_MIN_SOC_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_FORECAST_HORIZON_HOURS,
    CONF_HISTORY_CORRECTION_PERCENT,
    CONF_HISTORY_LEARNING_DAYS,
    CONF_HOME_ENERGY_ENTITY,
    CONF_INTERVAL_MINUTES,
    CONF_MANAGED_ENERGY_ENTITIES,
    CONF_MANAGED_ENERGY_ENTITY,
    CONF_MIN_BASELINE_KWH_PER_HOUR,
    CONF_REQUESTED_ENERGY_ENTITY,
    CONF_SOLCAST_ADDITIONAL_ENTITIES,
    CONF_SOLCAST_TODAY_ENTITY,
    CONF_SOLCAST_TOMORROW_ENTITY,
    CONF_UPDATE_INTERVAL_MINUTES,
    DEFAULT_UPDATE_INTERVAL_MINUTES,
    DOMAIN,
    MANAGED_LOAD_SUBENTRY,
)
from custom_components.energy_planner.coordinator import (
    EnergyPlannerCoordinator,
    _add_surplus_allocation,
    _async_planner_history_from_ha,
    _consumption_from_hourly_profile,
    _solcast_entity_ids,
    _solcast_forecast,
    build_planner_result,
)
from custom_components.energy_planner.history import EnergyHistory
from custom_components.energy_planner.models import PlannerResult
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


def test_coordinator_default_update_interval_is_60_minutes(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})

    coordinator = EnergyPlannerCoordinator(hass, entry)

    assert coordinator.update_interval == timedelta(
        minutes=DEFAULT_UPDATE_INTERVAL_MINUTES
    )


def test_coordinator_update_interval_is_independent_from_planning_interval(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={
            CONF_UPDATE_INTERVAL_MINUTES: 45,
            CONF_INTERVAL_MINUTES: 5,
        },
    )

    coordinator = EnergyPlannerCoordinator(hass, entry)

    assert coordinator.update_interval == timedelta(minutes=45)


async def test_recorder_history_includes_live_current_hour(
    hass,
    monkeypatch,
):
    now = datetime(2026, 7, 3, 12, 30)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOME_ENERGY_ENTITY: "sensor.home_energy_total",
            CONF_MANAGED_ENERGY_ENTITIES: ["sensor.ev_energy_total"],
        },
    )
    recorder_history = EnergyHistory()
    recorder_history.add_hourly_sample(
        now - timedelta(hours=1),
        home_kwh=1.5,
        managed_kwh=0.3,
        managed_source_id="sensor.ev_energy_total",
        observed_source_ids={"sensor.ev_energy_total"},
    )
    recorder_history.dirty = False
    live_history = EnergyHistory()
    live_history.add_hourly_sample(
        now,
        home_kwh=0.5,
        managed_kwh=0.4,
        managed_source_id="sensor.ev_energy_total",
        observed_source_ids={"sensor.ev_energy_total"},
    )

    async def recorder_statistics(*args, **kwargs):
        return recorder_history

    monkeypatch.setattr(
        "custom_components.energy_planner.coordinator."
        "async_get_recorder_energy_statistics",
        recorder_statistics,
    )

    planner_history = await _async_planner_history_from_ha(
        hass,
        entry,
        now=now,
        learning_days=3,
        fallback_history=live_history,
        warnings=[],
    )

    assert planner_history.source == "ha_statistics"
    assert (
        planner_history.history.managed_source_current_hour_kwh(
            "sensor.ev_energy_total",
            now=now,
        )
        == 0.4
    )
    assert (
        planner_history.history.managed_source_today_kwh(
            "sensor.ev_energy_total",
            now=now,
        )
        == 0.7
    )


async def test_coordinator_saves_internal_history_only_when_dirty(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    coordinator = EnergyPlannerCoordinator(hass, entry)
    coordinator._history_store.async_save = AsyncMock()

    await coordinator._async_save_history_if_changed()
    coordinator._history_store.async_save.assert_not_awaited()

    coordinator.history.dirty = True
    await coordinator._async_save_history_if_changed()
    coordinator._history_store.async_save.assert_awaited_once_with(coordinator.history)


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


def test_solcast_forecast_without_configured_entities_is_not_a_warning(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    warnings: list[str] = []

    assert _solcast_forecast(hass, entry, warnings) == []
    assert warnings == []


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


def test_build_planner_result_uses_hour_of_day_history_for_soc_forecast(hass):
    now = datetime(2026, 7, 3, 23, 0)
    history = EnergyHistory()
    for hours_ago in range(1, 25):
        history.add_hourly_sample(
            now - timedelta(hours=hours_ago),
            home_kwh=0.171,
        )

    hass.states.async_set("sensor.battery_soc", "100")
    hass.states.async_set("sensor.battery_capacity", "10")
    hass.states.async_set("sensor.battery_min_soc", "20")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_BATTERY_SOC_ENTITY: "sensor.battery_soc",
            CONF_BATTERY_CAPACITY_ENTITY: "sensor.battery_capacity",
            CONF_BATTERY_MIN_SOC_ENTITY: "sensor.battery_min_soc",
            CONF_HOME_ENERGY_ENTITY: "sensor.home_energy_total",
        },
        options={
            CONF_FORECAST_HORIZON_HOURS: 24,
            CONF_HISTORY_LEARNING_DAYS: 1,
            CONF_HISTORY_CORRECTION_PERCENT: 0,
            CONF_INTERVAL_MINUTES: 60,
            CONF_MIN_BASELINE_KWH_PER_HOUR: 0,
        },
    )

    result = build_planner_result(hass, entry, history=history, now=now)

    assert result.state == "ok"
    assert result.plan["soc_forecast_24h"]["soc_percent"] == 57
    assert all(
        point["consumption_kwh"] == 0.18
        for point in result.plan["soc_forecast"]["points"]
    )


def test_surplus_allocation_uses_daily_history_and_requested_override(hass):
    now = datetime(2026, 7, 21, 12, 0)
    history = EnergyHistory()
    for days_ago in range(1, 8):
        day_start = (now - timedelta(days=days_ago)).replace(hour=0)
        for hour in range(24):
            history.add_hourly_sample(
                day_start + timedelta(hours=hour),
                home_kwh=0,
                managed_kwh=3 if hour == 12 else 0,
                managed_source_id="sensor.boiler_energy_total",
                observed_source_ids={"sensor.boiler_energy_total"},
            )
    hass.states.async_set(
        "input_number.ev_requested_energy",
        "9",
        {"unit_of_measurement": "kWh"},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={CONF_HISTORY_LEARNING_DAYS: 7},
        version=2,
        subentries_data=(
            {
                "data": {CONF_MANAGED_ENERGY_ENTITY: "sensor.boiler_energy_total"},
                "subentry_type": MANAGED_LOAD_SUBENTRY,
                "title": "Boiler",
                "unique_id": "sensor.boiler_energy_total",
            },
            {
                "data": {
                    CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total",
                    CONF_REQUESTED_ENERGY_ENTITY: "input_number.ev_requested_energy",
                },
                "subentry_type": MANAGED_LOAD_SUBENTRY,
                "title": "EV",
                "unique_id": "sensor.ev_energy_total",
            },
        ),
    )
    result = PlannerResult(
        state="ok",
        updated=now,
        plan={
            "unused_surplus_tomorrow_kwh": 8,
            "unused_surplus_tomorrow_coverage_percent": 100,
            "unused_surplus_tomorrow_solar_coverage_percent": 100,
        },
    )
    warnings: list[str] = []

    _add_surplus_allocation(
        hass,
        entry,
        history=history,
        now=now,
        result=result,
        warnings=warnings,
    )

    loads = result.plan["surplus_allocation"]["loads"]
    assert loads["sensor.boiler_energy_total"]["method"] == "history"
    assert loads["sensor.boiler_energy_total"]["expected_demand_kwh"] == 3
    assert loads["sensor.ev_energy_total"]["method"] == "requested"
    assert loads["sensor.ev_energy_total"]["expected_demand_kwh"] == 9
    assert loads["sensor.boiler_energy_total"]["recommended_kwh"] == 2
    assert loads["sensor.ev_energy_total"]["recommended_kwh"] == 6
    assert result.plan["managed_recommended_tomorrow_kwh"] == 8
    assert warnings == []
