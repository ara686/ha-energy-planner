from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.energy_planner.const import (
    CONF_BATTERY_CAPACITY_ENTITY,
    CONF_BATTERY_MIN_SOC_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_BOTTOM_TEMPERATURE_ENTITY,
    CONF_CHARGING_EFFICIENCY,
    CONF_FORECAST_HORIZON_HOURS,
    CONF_HEATER_POWER_KW,
    CONF_HISTORY_CORRECTION_PERCENT,
    CONF_HISTORY_LEARNING_DAYS,
    CONF_HOME_ENERGY_ENTITY,
    CONF_INTERVAL_MINUTES,
    CONF_MANAGED_ENERGY_ENTITIES,
    CONF_MANAGED_ENERGY_ENTITY,
    CONF_MANAGED_LOAD_TYPE,
    CONF_MAXIMUM_CHARGING_POWER_KW,
    CONF_MAXIMUM_TEMPERATURE_C,
    CONF_MIN_BASELINE_KWH_PER_HOUR,
    CONF_MINIMUM_TEMPERATURE_C,
    CONF_PRIORITY,
    CONF_REQUESTED_ENERGY_ENTITY,
    CONF_REQUIRED_ENERGY_ENTITY,
    CONF_SOLCAST_ADDITIONAL_ENTITIES,
    CONF_SOLCAST_TODAY_ENTITY,
    CONF_SOLCAST_TOMORROW_ENTITY,
    CONF_TANK_VOLUME_LITERS,
    CONF_THERMAL_CONVERSION_FACTOR,
    CONF_TOP_TEMPERATURE_ENTITY,
    CONF_UPDATE_INTERVAL_MINUTES,
    DEFAULT_UPDATE_INTERVAL_MINUTES,
    DOMAIN,
    MANAGED_LOAD_SUBENTRY,
    MANAGED_LOAD_TYPE_ELECTRIC_VEHICLE,
    MANAGED_LOAD_TYPE_GENERIC,
    MANAGED_LOAD_TYPE_HOT_WATER,
)
from custom_components.energy_planner.coordinator import (
    EnergyPlannerCoordinator,
    _add_managed_soc_forecast,
    _add_surplus_allocation,
    _async_planner_history_from_ha,
    _consumption_from_hourly_profile,
    _remaining_today_surplus_slots,
    _solcast_entity_ids,
    _solcast_forecast,
    build_planner_result,
)
from custom_components.energy_planner.history import EnergyHistory
from custom_components.energy_planner.models import (
    ForecastSlot,
    PlannerInput,
    PlannerResult,
    TimeWindow,
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


def test_coordinator_normalizes_mwh_energy_source_states_to_kwh(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    coordinator = EnergyPlannerCoordinator(hass, entry)

    hass.states.async_set(
        "sensor.inverter_total_load_consumption",
        "12",
        {"unit_of_measurement": "MWh"},
    )
    coordinator.record_energy_source_state(
        entity_id="sensor.inverter_total_load_consumption",
        source_type="home",
        state=hass.states.get("sensor.inverter_total_load_consumption"),
    )
    hass.states.async_set(
        "sensor.inverter_total_load_consumption",
        "12.001",
        {"unit_of_measurement": "MWh"},
    )
    coordinator.record_energy_source_state(
        entity_id="sensor.inverter_total_load_consumption",
        source_type="home",
        state=hass.states.get("sensor.inverter_total_load_consumption"),
    )

    bucket = next(iter(coordinator.history.buckets.values()))
    assert round(bucket.home_kwh, 6) == 1.0


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


def test_build_planner_result_adds_soc_forecast_with_managed_estimates(hass):
    now = datetime(2026, 7, 21, 12, 0)
    source_id = "sensor.boiler_energy_total"
    history = EnergyHistory()
    for days_ago in range(1, 8):
        day_start = (now - timedelta(days=days_ago)).replace(hour=0)
        for hour in range(24):
            managed_kwh = 3 if hour == 12 else 0
            history.add_hourly_sample(
                day_start + timedelta(hours=hour),
                home_kwh=1 + managed_kwh,
                managed_kwh=managed_kwh,
                managed_source_id=source_id,
                observed_source_ids={source_id},
            )

    hass.states.async_set("sensor.battery_soc", "100")
    hass.states.async_set("sensor.battery_capacity", "100")
    hass.states.async_set("sensor.battery_min_soc", "0")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_BATTERY_SOC_ENTITY: "sensor.battery_soc",
            CONF_BATTERY_CAPACITY_ENTITY: "sensor.battery_capacity",
            CONF_BATTERY_MIN_SOC_ENTITY: "sensor.battery_min_soc",
            CONF_HOME_ENERGY_ENTITY: "sensor.home_energy_total",
        },
        options={
            CONF_FORECAST_HORIZON_HOURS: 48,
            CONF_HISTORY_LEARNING_DAYS: 7,
            CONF_HISTORY_CORRECTION_PERCENT: 0,
            CONF_INTERVAL_MINUTES: 60,
            CONF_MIN_BASELINE_KWH_PER_HOUR: 0,
        },
        version=2,
        subentries_data=(
            {
                "data": {CONF_MANAGED_ENERGY_ENTITY: source_id},
                "subentry_type": MANAGED_LOAD_SUBENTRY,
                "title": "Boiler",
                "unique_id": source_id,
            },
        ),
    )

    result = build_planner_result(hass, entry, history=history, now=now)

    managed_forecast = result.plan["soc_forecast_with_managed"]
    assert len(result.plan["managed_allocation_by_day"]) == 1
    assert result.plan["managed_expected_demand_tomorrow_kwh"] == 3
    assert result.plan["soc_at_forecast_horizon_with_managed"] == (
        result.plan["soc_at_forecast_horizon"] - 3
    )
    assert managed_forecast["managed_expected_kwh"] == 3
    assert managed_forecast["managed_scheduled_kwh"] == 3
    assert managed_forecast["managed_scheduled_by_source"] == {source_id: 3}
    assert managed_forecast["fallback_source_ids"] == []
    managed_points = [
        point
        for point in managed_forecast["points"]
        if point.get("managed_consumption_kwh", 0) > 0
    ]
    assert len(managed_points) == 1
    assert managed_points[0]["timestamp"] == "2026-07-22T12:00:00"
    assert managed_points[0]["managed_consumption_kwh"] == 3


def test_hot_water_allocation_repeats_demand_for_complete_future_days(hass):
    now = datetime(2026, 8, 18, 12)
    entry = _hot_water_entry()
    _set_hot_water_temperatures(hass, top="122", bottom="86", unit="°F")
    result = PlannerResult(
        state="ok",
        updated=now,
        plan={
            "unused_surplus_by_day": [
                {"date": "2026-08-19", "complete": True},
                {"date": "2026-08-20", "complete": True},
            ],
            "soc_forecast": {
                "points": [
                    {
                        "timestamp": "2026-08-19T10:00:00",
                        "unused_surplus_kwh": 5,
                    },
                    {
                        "timestamp": "2026-08-20T10:00:00",
                        "unused_surplus_kwh": 1,
                    },
                ]
            },
        },
    )
    warnings: list[str] = []

    allocations = _add_surplus_allocation(
        hass,
        entry,
        history=EnergyHistory(),
        now=now,
        result=result,
        warnings=warnings,
    )

    first, second = allocations
    first_load = first.as_dict()["loads"]["sensor.boiler_energy_total"]
    second_load = second.as_dict()["loads"]["sensor.boiler_energy_total"]
    assert first_load["method"] == "thermal_model"
    assert first_load["average_temperature"] == 40
    assert first_load["minimum_required_kwh"] == 1.163
    assert second_load["minimum_required_kwh"] == 1.163
    assert first_load["recommended_kwh"] == 5
    assert second_load["recommended_kwh"] == 1
    assert second_load["minimum_shortfall_kwh"] == 0.163
    assert result.plan["surplus_allocation"] == first.as_dict()
    assert warnings == []


def test_hot_water_missing_temperature_withholds_only_its_recommendation(hass):
    now = datetime(2026, 8, 18, 12)
    entry = _hot_water_entry()
    _set_hot_water_temperatures(hass, top="50", bottom="unavailable")
    history = EnergyHistory()
    history.add_hourly_sample(
        now - timedelta(days=1),
        home_kwh=12,
        managed_kwh=10,
        managed_source_id="sensor.boiler_energy_total",
        observed_source_ids={"sensor.boiler_energy_total"},
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

    load = result.plan["surplus_allocation"]["loads"]["sensor.boiler_energy_total"]
    assert load["state"] == "insufficient_data"
    assert load["method"] == "insufficient_data"
    assert load["recommended_kwh"] is None
    assert load["reason"] == "invalid_temperature_source"
    assert any("sensor.boiler_bottom_temperature" in item for item in warnings)


def test_hot_water_allocation_covers_all_25_hours_of_fall_dst_day(hass):
    timezone = ZoneInfo("Europe/Prague")
    now = datetime(2026, 10, 24, 12, tzinfo=timezone)
    entry = _hot_water_entry(
        minimum_temperature_c=1,
        maximum_temperature_c=70,
        tank_volume_liters=1000,
        heater_power_kw=1,
    )
    _set_hot_water_temperatures(hass, top="0", bottom="0")
    first_utc = datetime(2026, 10, 24, 22, tzinfo=UTC)
    points = [
        {
            "timestamp": (first_utc + timedelta(hours=index)).astimezone(timezone),
            "unused_surplus_kwh": 1,
        }
        for index in range(25)
    ]
    result = PlannerResult(
        state="ok",
        updated=now,
        plan={
            "unused_surplus_by_day": [{"date": "2026-10-25", "complete": True}],
            "soc_forecast": {"points": points},
        },
    )

    allocations = _add_surplus_allocation(
        hass,
        entry,
        history=EnergyHistory(),
        now=now,
        result=result,
        warnings=[],
    )

    assert allocations[0].available_surplus_kwh == 25
    assert allocations[0].recommended_kwh == 25
    assert len(allocations[0].hot_water_energy_by_slot) == 25


def test_hot_water_soc_forecast_uses_only_allocated_surplus_slots(hass):
    now = datetime(2026, 8, 18, 12)
    slot_starts = [datetime(2026, 8, 19, 10), datetime(2026, 8, 19, 11)]
    entry = _hot_water_entry(heater_power_kw=1)
    _set_hot_water_temperatures(hass, top="50", bottom="30")
    result = PlannerResult(
        state="ok",
        updated=now,
        plan={
            "unused_surplus_by_day": [{"date": "2026-08-19", "complete": True}],
            "soc_forecast": {
                "points": [
                    {"timestamp": start, "unused_surplus_kwh": 1}
                    for start in slot_starts
                ]
            },
        },
    )
    history = EnergyHistory()
    allocations = _add_surplus_allocation(
        hass,
        entry,
        history=history,
        now=now,
        result=result,
        warnings=[],
    )
    planner_input = PlannerInput(
        now=now,
        battery_soc=100,
        battery_capacity_kwh=10,
        battery_min_soc=0,
        slots=[ForecastSlot(start, 0, 0) for start in slot_starts],
        nt_windows=[],
        charge_window=TimeWindow("00:00", "00:00"),
        grid_charging_enabled=False,
        interval_minutes=60,
        forecast_horizon_hours=24,
    )

    _add_managed_soc_forecast(
        planner_input=planner_input,
        history=history,
        now=now,
        allocations=allocations,
        result=result,
    )

    forecast = result.plan["soc_forecast_with_managed"]
    assert forecast["managed_expected_kwh"] == 2
    assert forecast["managed_scheduled_kwh"] == 2
    assert forecast["managed_scheduled_by_source"] == {"sensor.boiler_energy_total": 2}
    assert [point["managed_consumption_kwh"] for point in forecast["points"]] == [
        1,
        1,
    ]
    assert result.plan["soc_at_forecast_horizon_with_managed"] == 80


def test_ev_allocation_uses_remaining_today_then_carries_across_days(hass):
    now = datetime(2026, 8, 18, 12, 30)
    entry = _electric_vehicle_entry(include_generic=True, maximum_power_kw=2)
    _set_electric_vehicle_inputs(hass, battery_required="9")
    hass.states.async_set(
        "input_number.generic_requested_energy",
        "2",
        {"unit_of_measurement": "kWh"},
    )
    today_points = [
        {
            "timestamp": datetime(2026, 8, 18, hour),
            "unused_surplus_kwh": 1 if hour < 17 else 0,
            "solar_coverage": 1,
        }
        for hour in range(13, 24)
    ]
    tomorrow_points = [
        {
            "timestamp": datetime(2026, 8, 19, hour),
            "unused_surplus_kwh": 1 if hour < 4 else 0,
        }
        for hour in range(24)
    ]
    third_day_points = [
        {
            "timestamp": datetime(2026, 8, 20, hour),
            "unused_surplus_kwh": 1 if hour < 4 else 0,
        }
        for hour in range(24)
    ]
    result = PlannerResult(
        state="ok",
        updated=now,
        plan={
            "unused_surplus_by_day": [
                {"date": "2026-08-19", "complete": True},
                {"date": "2026-08-20", "complete": True},
            ],
            "soc_forecast": {
                "points": [*today_points, *tomorrow_points, *third_day_points]
            },
        },
    )

    allocations = _add_surplus_allocation(
        hass,
        entry,
        history=EnergyHistory(),
        now=now,
        result=result,
        warnings=[],
    )

    today, tomorrow, third_day = allocations
    today_ev = today.as_dict()["loads"]["sensor.ev_energy_total"]
    tomorrow_loads = tomorrow.as_dict()["loads"]
    tomorrow_ev = tomorrow_loads["sensor.ev_energy_total"]
    third_day_loads = third_day.as_dict()["loads"]
    third_day_ev = third_day_loads["sensor.ev_energy_total"]
    assert today_ev["recommended_kwh"] == 4
    assert today_ev["electrical_shortfall_kwh"] == 6
    assert tomorrow_ev["electrical_remaining_before_kwh"] == 6
    assert tomorrow_ev["recommended_kwh"] == 4
    assert tomorrow_ev["electrical_shortfall_kwh"] == 2
    assert tomorrow_loads["sensor.generic_energy_total"]["recommended_kwh"] == 0
    assert third_day_ev["electrical_remaining_before_kwh"] == 2
    assert third_day_ev["recommended_kwh"] == 2
    assert "sensor.generic_energy_total" not in third_day_loads
    assert result.plan["managed_recommended_today_kwh"] == 4
    assert result.plan["managed_recommended_tomorrow_kwh"] == 4


def test_incomplete_today_ev_data_carries_full_request_to_tomorrow(hass):
    now = datetime(2026, 8, 18, 22, 30)
    entry = _electric_vehicle_entry(maximum_power_kw=20)
    _set_electric_vehicle_inputs(hass, battery_required="9")
    result = PlannerResult(
        state="ok",
        updated=now,
        plan={
            "unused_surplus_by_day": [{"date": "2026-08-19", "complete": True}],
            "soc_forecast": {
                "points": [
                    {
                        "timestamp": datetime(2026, 8, 18, 23),
                        "unused_surplus_kwh": 10,
                        "solar_coverage": 0.5,
                    },
                    {
                        "timestamp": datetime(2026, 8, 19, 10),
                        "unused_surplus_kwh": 10,
                    },
                ]
            },
        },
    )

    allocations = _add_surplus_allocation(
        hass,
        entry,
        history=EnergyHistory(),
        now=now,
        result=result,
        warnings=[],
    )

    today_ev = allocations[0].as_dict()["loads"]["sensor.ev_energy_total"]
    tomorrow_ev = allocations[1].as_dict()["loads"]["sensor.ev_energy_total"]
    assert result.plan["managed_recommended_today_kwh"] is None
    assert today_ev["state"] == "insufficient_data"
    assert tomorrow_ev["electrical_remaining_before_kwh"] == 10
    assert tomorrow_ev["recommended_kwh"] == 10


def test_ev_with_no_remaining_today_slot_recommends_zero_today(hass):
    now = datetime(2026, 8, 18, 23, 59)
    entry = _electric_vehicle_entry(maximum_power_kw=20)
    _set_electric_vehicle_inputs(hass, battery_required="9")
    result = PlannerResult(
        state="ok",
        updated=now,
        plan={
            "unused_surplus_by_day": [{"date": "2026-08-19", "complete": True}],
            "soc_forecast": {
                "points": [
                    {
                        "timestamp": datetime(2026, 8, 19, 10),
                        "unused_surplus_kwh": 10,
                    }
                ]
            },
        },
    )

    allocations = _add_surplus_allocation(
        hass,
        entry,
        history=EnergyHistory(),
        now=now,
        result=result,
        warnings=[],
    )

    assert allocations[0].recommended_kwh == 0
    assert result.plan["managed_recommended_today_kwh"] == 0
    assert allocations[1].expected_demand_kwh == 10


def test_invalid_ev_input_is_unavailable_without_history_fallback(hass):
    now = datetime(2026, 8, 18, 23, 59)
    entry = _electric_vehicle_entry()
    _set_electric_vehicle_inputs(
        hass,
        battery_required="unavailable",
    )
    history = EnergyHistory()
    for days_ago in range(1, 8):
        history.add_hourly_sample(
            now - timedelta(days=days_ago),
            home_kwh=8,
            managed_kwh=8,
            managed_source_id="sensor.ev_energy_total",
            observed_source_ids={"sensor.ev_energy_total"},
        )
    result = PlannerResult(
        state="ok",
        updated=now,
        plan={
            "unused_surplus_by_day": [{"date": "2026-08-19", "complete": True}],
            "soc_forecast": {
                "points": [
                    {
                        "timestamp": datetime(2026, 8, 19, 10),
                        "unused_surplus_kwh": 10,
                    }
                ]
            },
        },
    )
    warnings: list[str] = []

    allocations = _add_surplus_allocation(
        hass,
        entry,
        history=history,
        now=now,
        result=result,
        warnings=warnings,
    )

    load = allocations[1].as_dict()["loads"]["sensor.ev_energy_total"]
    assert result.plan["managed_recommended_today_kwh"] is None
    assert load["method"] == "insufficient_data"
    assert load["recommended_kwh"] is None
    assert load["reason"] == "invalid_required_energy_source"
    assert any("sensor.enyaq_charge_kwh" in warning for warning in warnings)


def test_invalid_configured_ev_power_is_unavailable(hass):
    now = datetime(2026, 8, 18, 23, 59)
    entry = _electric_vehicle_entry(maximum_power_kw=0)
    _set_electric_vehicle_inputs(hass, battery_required="9")
    result = PlannerResult(
        state="ok",
        updated=now,
        plan={
            "unused_surplus_by_day": [{"date": "2026-08-19", "complete": True}],
            "soc_forecast": {
                "points": [
                    {
                        "timestamp": datetime(2026, 8, 19, 10),
                        "unused_surplus_kwh": 10,
                    }
                ]
            },
        },
    )
    warnings: list[str] = []

    allocations = _add_surplus_allocation(
        hass,
        entry,
        history=EnergyHistory(),
        now=now,
        result=result,
        warnings=warnings,
    )

    load = allocations[1].as_dict()["loads"]["sensor.ev_energy_total"]
    assert load["recommended_kwh"] is None
    assert load["reason"] == "invalid_maximum_charging_power"
    assert any("maximum charging power" in warning for warning in warnings)


def test_remaining_today_ev_slots_cover_repeated_fall_dst_hour():
    timezone = ZoneInfo("Europe/Prague")
    now = datetime(2026, 10, 25, 0, 30, tzinfo=timezone)
    first_utc = datetime(2026, 10, 24, 23, tzinfo=UTC)
    points = [
        {
            "timestamp": (first_utc + timedelta(hours=index)).astimezone(timezone),
            "unused_surplus_kwh": 1,
            "solar_coverage": 1,
        }
        for index in range(24)
    ]

    slots, complete = _remaining_today_surplus_slots(
        points,
        now=now,
        interval_minutes=60,
    )

    assert complete
    assert len(slots) == 24
    assert len({slot.start.astimezone(UTC) for slot in slots}) == 24


def test_remaining_today_ev_slots_skip_missing_spring_dst_hour():
    timezone = ZoneInfo("Europe/Prague")
    now = datetime(2026, 3, 29, 0, 30, tzinfo=timezone)
    first_utc = datetime(2026, 3, 29, 0, tzinfo=UTC)
    points = [
        {
            "timestamp": (first_utc + timedelta(hours=index)).astimezone(timezone),
            "unused_surplus_kwh": 1,
            "solar_coverage": 1,
        }
        for index in range(22)
    ]

    slots, complete = _remaining_today_surplus_slots(
        points,
        now=now,
        interval_minutes=60,
    )

    assert complete
    assert len(slots) == 22
    assert all(slot.start.hour != 2 for slot in slots)


def test_ev_soc_forecast_uses_only_allocated_solar_slots(hass):
    now = datetime(2026, 8, 18, 21, 30)
    entry = _electric_vehicle_entry(maximum_power_kw=1)
    _set_electric_vehicle_inputs(hass, battery_required="1.8")
    slot_starts = [datetime(2026, 8, 18, 22), datetime(2026, 8, 18, 23)]
    result = PlannerResult(
        state="ok",
        updated=now,
        plan={
            "unused_surplus_by_day": [{"date": "2026-08-19", "complete": False}],
            "soc_forecast": {
                "points": [
                    {
                        "timestamp": start,
                        "unused_surplus_kwh": 1,
                        "solar_coverage": 1,
                    }
                    for start in slot_starts
                ]
            },
        },
    )
    history = EnergyHistory()
    allocations = _add_surplus_allocation(
        hass,
        entry,
        history=history,
        now=now,
        result=result,
        warnings=[],
    )
    planner_input = PlannerInput(
        now=now,
        battery_soc=100,
        battery_capacity_kwh=10,
        battery_min_soc=0,
        slots=[ForecastSlot(start, 0, 0) for start in slot_starts],
        nt_windows=[],
        charge_window=TimeWindow("00:00", "00:00"),
        grid_charging_enabled=False,
        interval_minutes=60,
        forecast_horizon_hours=24,
    )

    _add_managed_soc_forecast(
        planner_input=planner_input,
        history=history,
        now=now,
        allocations=allocations,
        result=result,
    )

    forecast = result.plan["soc_forecast_with_managed"]
    assert forecast["managed_scheduled_kwh"] == 2
    assert forecast["managed_scheduled_by_source"] == {"sensor.ev_energy_total": 2}
    assert [point["managed_consumption_kwh"] for point in forecast["points"]] == [
        1,
        1,
    ]


def _electric_vehicle_entry(
    *, include_generic: bool = False, maximum_power_kw: float = 11
) -> MockConfigEntry:
    subentries = [
        {
            "data": {
                CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total",
                CONF_MANAGED_LOAD_TYPE: MANAGED_LOAD_TYPE_ELECTRIC_VEHICLE,
                CONF_PRIORITY: 10,
                CONF_REQUIRED_ENERGY_ENTITY: "sensor.enyaq_charge_kwh",
                CONF_MAXIMUM_CHARGING_POWER_KW: maximum_power_kw,
                CONF_CHARGING_EFFICIENCY: 0.9,
            },
            "subentry_type": MANAGED_LOAD_SUBENTRY,
            "title": "EV",
            "unique_id": "sensor.ev_energy_total",
        }
    ]
    if include_generic:
        subentries.append(
            {
                "data": {
                    CONF_MANAGED_ENERGY_ENTITY: "sensor.generic_energy_total",
                    CONF_MANAGED_LOAD_TYPE: MANAGED_LOAD_TYPE_GENERIC,
                    CONF_PRIORITY: 100,
                    CONF_REQUESTED_ENERGY_ENTITY: (
                        "input_number.generic_requested_energy"
                    ),
                },
                "subentry_type": MANAGED_LOAD_SUBENTRY,
                "title": "Generic",
                "unique_id": "sensor.generic_energy_total",
            }
        )
    return MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={CONF_INTERVAL_MINUTES: 60},
        version=4,
        subentries_data=tuple(subentries),
    )


def _set_electric_vehicle_inputs(
    hass,
    *,
    battery_required: str,
) -> None:
    hass.states.async_set(
        "sensor.enyaq_charge_kwh",
        battery_required,
        {"device_class": "energy_storage", "unit_of_measurement": "kWh"},
    )


def _hot_water_entry(
    *,
    minimum_temperature_c: float = 45,
    maximum_temperature_c: float = 70,
    tank_volume_liters: float = 200,
    heater_power_kw: float = 10,
) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={CONF_INTERVAL_MINUTES: 60},
        version=3,
        subentries_data=(
            {
                "data": {
                    CONF_MANAGED_ENERGY_ENTITY: "sensor.boiler_energy_total",
                    CONF_MANAGED_LOAD_TYPE: MANAGED_LOAD_TYPE_HOT_WATER,
                    CONF_PRIORITY: 10,
                    CONF_TOP_TEMPERATURE_ENTITY: "sensor.boiler_top_temperature",
                    CONF_BOTTOM_TEMPERATURE_ENTITY: (
                        "sensor.boiler_bottom_temperature"
                    ),
                    CONF_MINIMUM_TEMPERATURE_C: minimum_temperature_c,
                    CONF_MAXIMUM_TEMPERATURE_C: maximum_temperature_c,
                    CONF_TANK_VOLUME_LITERS: tank_volume_liters,
                    CONF_HEATER_POWER_KW: heater_power_kw,
                    CONF_THERMAL_CONVERSION_FACTOR: 1,
                },
                "subentry_type": MANAGED_LOAD_SUBENTRY,
                "title": "Boiler",
                "unique_id": "sensor.boiler_energy_total",
            },
        ),
    )


def _set_hot_water_temperatures(
    hass,
    *,
    top: str,
    bottom: str,
    unit: str = "°C",
) -> None:
    attributes = {"device_class": "temperature", "unit_of_measurement": unit}
    hass.states.async_set("sensor.boiler_top_temperature", top, attributes)
    hass.states.async_set("sensor.boiler_bottom_temperature", bottom, attributes)
