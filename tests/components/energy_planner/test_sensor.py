from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import EntityCategory
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.energy_planner.binary_sensor import BINARY_SENSOR_DESCRIPTIONS
from custom_components.energy_planner.const import (
    CONF_BOTTOM_TEMPERATURE_ENTITY,
    CONF_CHARGE_WINDOW,
    CONF_CHARGING_EFFICIENCY,
    CONF_EV_CHARGING_STRATEGY,
    CONF_EV_CONNECTED_ENTITY,
    CONF_EV_DEPARTURE_TIME,
    CONF_EV_GRID_OUTSIDE_NT_ENTITY,
    CONF_EV_PRESENCE_ENTITY,
    CONF_EV_RETURN_TIME,
    CONF_EV_WORKDAYS,
    CONF_FORECAST_HORIZON_HOURS,
    CONF_GRID_CHARGING_ENABLED,
    CONF_HEATER_POWER_KW,
    CONF_HISTORY_LEARNING_DAYS,
    CONF_MANAGED_ENERGY_ENTITY,
    CONF_MANAGED_LOAD_TYPE,
    CONF_MAXIMUM_CHARGING_POWER_KW,
    CONF_MAXIMUM_TEMPERATURE_C,
    CONF_MINIMUM_TEMPERATURE_C,
    CONF_NT_WINDOWS,
    CONF_PRIORITY,
    CONF_REQUIRED_ENERGY_ENTITY,
    CONF_TANK_VOLUME_LITERS,
    CONF_THERMAL_CONVERSION_FACTOR,
    CONF_TOP_TEMPERATURE_ENTITY,
    CONF_UPDATE_INTERVAL_MINUTES,
    DOMAIN,
    EV_CHARGING_STRATEGY_DEADLINE_AWARE,
    MANAGED_LOAD_SUBENTRY,
    MANAGED_LOAD_TYPE_ELECTRIC_VEHICLE,
    MANAGED_LOAD_TYPE_GENERIC,
    MANAGED_LOAD_TYPE_HOT_WATER,
)
from custom_components.energy_planner.history import (
    EnergyHistory,
    EnergyHistoryStore,
    hour_key,
)
from custom_components.energy_planner.models import PlannerResult
from custom_components.energy_planner.sensor import (
    EV_PLAN_SENSOR_DESCRIPTIONS,
    MANAGED_SOURCE_SENSOR_DESCRIPTIONS,
    SENSOR_DESCRIPTIONS,
    EnergyPlannerManagedSourceSensor,
    EnergyPlannerSensor,
    _charge_window_option_value,
    _consumption_history_attributes,
    _consumption_history_value,
    _soc_forecast_attributes,
    _soc_forecast_with_managed_attributes,
    _windows_option_value,
)

from .conftest import config_data, options_data, set_source_states


async def test_setup_entry_creates_all_sensors(hass, config_entry):
    set_source_states(hass)
    config_entry.add_to_hass(hass)

    device_registry = dr.async_get(hass)
    parent_device = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, config_entry.entry_id)},
        name=config_entry.title,
    )
    entity_registry = er.async_get(hass)
    existing_managed_entity = entity_registry.async_get_or_create(
        SENSOR_DOMAIN,
        DOMAIN,
        (f"{config_entry.entry_id}_managed_{slugify('sensor.ev_energy_total')}_today"),
        config_entry=config_entry,
        device_id=parent_device.id,
    )

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED

    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, config_entry.entry_id)
    entity_ids = {entity.unique_id: entity.entity_id for entity in entities}

    assert len(entity_ids) == (
        len(SENSOR_DESCRIPTIONS)
        + len(BINARY_SENSOR_DESCRIPTIONS)
        + 2 * len(MANAGED_SOURCE_SENSOR_DESCRIPTIONS)
    )

    target_state = hass.states.get(entity_ids[f"{config_entry.entry_id}_target_soc"])
    assert target_state is not None
    assert target_state.attributes["unit_of_measurement"] == "%"
    assert float(target_state.state) >= 20.0

    planner_state = hass.states.get(entity_ids[f"{config_entry.entry_id}_state"])
    assert planner_state is not None
    assert planner_state.state in {"ok", "warning"}
    assert "warnings" in planner_state.attributes
    assert "plan" not in planner_state.attributes
    assert "forecast" not in planner_state.attributes

    parent_device = device_registry.async_get_device(
        identifiers={(DOMAIN, config_entry.entry_id)}
    )
    assert parent_device is not None

    managed_devices = {}
    for subentry in config_entry.subentries.values():
        source_entity_id = subentry.data[CONF_MANAGED_ENERGY_ENTITY]
        device = device_registry.async_get_device(
            identifiers={
                (
                    DOMAIN,
                    f"{config_entry.entry_id}_managed_load_{subentry.subentry_id}",
                )
            }
        )
        assert device is not None
        assert device.via_device_id == parent_device.id
        assert device.config_entries_subentries == {
            config_entry.entry_id: {subentry.subentry_id}
        }
        managed_devices[source_entity_id] = device

    assert set(managed_devices) == {
        "sensor.ev_energy_total",
        "sensor.water_heater_energy_total",
    }
    assert managed_devices["sensor.ev_energy_total"].name == "EV charging energy"
    assert managed_devices["sensor.water_heater_energy_total"].name == (
        "Water heater energy"
    )
    assert (
        managed_devices["sensor.ev_energy_total"].id
        != managed_devices["sensor.water_heater_energy_total"].id
    )

    migrated_managed_entity = registry.async_get(existing_managed_entity.entity_id)
    assert migrated_managed_entity is not None
    assert (
        migrated_managed_entity.device_id
        == managed_devices["sensor.ev_energy_total"].id
    )

    target_soc_entity = registry.async_get(
        entity_ids[f"{config_entry.entry_id}_target_soc"]
    )
    assert target_soc_entity is not None
    assert target_soc_entity.device_id == parent_device.id


async def test_point_payloads_are_excluded_from_recorder(hass, config_entry):
    set_source_states(hass)
    config_entry.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    soc_forecast_entity_id = registry.async_get_entity_id(
        SENSOR_DOMAIN,
        DOMAIN,
        f"{config_entry.entry_id}_soc_forecast",
    )
    soc_forecast = hass.states.get(soc_forecast_entity_id)

    assert soc_forecast is not None
    assert soc_forecast.state_info is not None
    assert "points" in soc_forecast.state_info["unrecorded_attributes"]
    expected_unrecorded = frozenset({"managed_allocation_by_day", "points"})
    assert EnergyPlannerSensor._unrecorded_attributes == expected_unrecorded
    assert EnergyPlannerManagedSourceSensor._unrecorded_attributes == frozenset(
        {"managed_allocation_by_day", "points", "timeline"}
    )


async def test_technical_sensors_are_diagnostic_entities(hass, config_entry):
    set_source_states(hass)
    config_entry.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, config_entry.entry_id)
    categories = {
        entity.unique_id.removeprefix(
            f"{config_entry.entry_id}_"
        ): entity.entity_category
        for entity in entities
    }

    assert categories["state"] is EntityCategory.DIAGNOSTIC
    assert categories["soc_at_planner_start"] is EntityCategory.DIAGNOSTIC
    assert categories["soc_at_lock_start"] is EntityCategory.DIAGNOSTIC
    assert categories["sun_start"] is EntityCategory.DIAGNOSTIC
    assert categories["lock_start"] is EntityCategory.DIAGNOSTIC
    assert categories["updated"] is EntityCategory.DIAGNOSTIC
    assert categories["history_status"] is EntityCategory.DIAGNOSTIC
    assert categories["consumption_history"] is EntityCategory.DIAGNOSTIC
    assert categories[CONF_UPDATE_INTERVAL_MINUTES] is EntityCategory.DIAGNOSTIC
    assert categories[CONF_HISTORY_LEARNING_DAYS] is EntityCategory.DIAGNOSTIC
    assert categories[CONF_NT_WINDOWS] is EntityCategory.DIAGNOSTIC
    assert categories[CONF_CHARGE_WINDOW] is EntityCategory.DIAGNOSTIC
    assert categories[CONF_FORECAST_HORIZON_HOURS] is EntityCategory.DIAGNOSTIC
    assert categories["target_soc"] is None
    assert categories["soc_forecast"] is None
    assert categories["soc_forecast_with_managed"] is None
    assert categories["soc_forecast_24h"] is None


async def test_horizon_soc_forecasts_use_battery_device_class(hass, config_entry):
    set_source_states(hass)
    config_entry.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, config_entry.entry_id)
    entity_ids = {entity.unique_id: entity.entity_id for entity in entities}

    soc_forecast = hass.states.get(entity_ids[f"{config_entry.entry_id}_soc_forecast"])
    assert soc_forecast is not None
    assert soc_forecast.attributes["device_class"] == "battery"
    assert soc_forecast.attributes["unit_of_measurement"] == "%"
    assert "state_class" not in soc_forecast.attributes

    managed_soc_forecast = hass.states.get(
        entity_ids[f"{config_entry.entry_id}_soc_forecast_with_managed"]
    )
    assert managed_soc_forecast is not None
    assert managed_soc_forecast.attributes["device_class"] == "battery"
    assert managed_soc_forecast.attributes["unit_of_measurement"] == "%"
    assert "state_class" not in managed_soc_forecast.attributes

    non_battery_soc_keys = (
        "lock_soc",
        "charge_to_soc",
        "target_soc",
        "safe_discharge_soc",
        "free_capacity_soc",
        "soc_at_planner_start",
        "soc_at_lock_start",
        "soc_forecast_24h",
    )
    for key in non_battery_soc_keys:
        state = hass.states.get(entity_ids[f"{config_entry.entry_id}_{key}"])
        assert state is not None
        assert state.attributes["unit_of_measurement"] == "%"
        assert state.attributes.get("device_class") != "battery"
        assert "state_class" not in state.attributes

    for key in (
        "unused_surplus_today_kwh",
        "unused_surplus_total_kwh",
        "unused_surplus_tomorrow_kwh",
        "managed_recommended_today_kwh",
        "managed_expected_demand_tomorrow_kwh",
        "managed_recommended_tomorrow_kwh",
        "unallocated_surplus_tomorrow_kwh",
        "vt_grid_import_kwh_at_target",
        "charged_kwh_total_at_target",
    ):
        state = hass.states.get(entity_ids[f"{config_entry.entry_id}_{key}"])
        assert state is not None
        assert "state_class" not in state.attributes


async def test_selected_soc_sensors_suggest_whole_number_display(
    hass,
    config_entry,
):
    set_source_states(hass)
    config_entry.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, config_entry.entry_id)
    entity_ids = {entity.unique_id: entity.entity_id for entity in entities}

    for key in ("safe_discharge_soc", "free_capacity_soc"):
        entity_id = entity_ids[f"{config_entry.entry_id}_{key}"]
        state = hass.states.get(entity_id)
        registry_entry = registry.async_get(entity_id)

        assert state is not None
        assert state.attributes["unit_of_measurement"] == "%"
        assert registry_entry is not None
        assert registry_entry.options[SENSOR_DOMAIN]["suggested_display_precision"] == 0


async def test_plan_binary_sensors_expose_charge_and_discharge_decisions(
    hass,
    config_entry,
):
    set_source_states(hass)
    config_entry.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED

    registry = er.async_get(hass)
    charge_now_entity_id = registry.async_get_entity_id(
        BINARY_SENSOR_DOMAIN,
        DOMAIN,
        f"{config_entry.entry_id}_charge_now",
    )
    discharge_allowed_entity_id = registry.async_get_entity_id(
        BINARY_SENSOR_DOMAIN,
        DOMAIN,
        f"{config_entry.entry_id}_discharge_allowed",
    )

    assert charge_now_entity_id is not None
    assert discharge_allowed_entity_id is not None

    config_entry.runtime_data.async_set_updated_data(
        PlannerResult(
            state="ok",
            updated=dt_util.utcnow(),
            plan={
                "soc_at_planner_start": 40,
                "charge_to_soc": 60,
                "safe_discharge_soc": 30,
            },
        )
    )
    await hass.async_block_till_done()

    charge_now = hass.states.get(charge_now_entity_id)
    discharge_allowed = hass.states.get(discharge_allowed_entity_id)

    assert charge_now is not None
    assert charge_now.state == STATE_ON
    assert discharge_allowed is not None
    assert discharge_allowed.state == STATE_ON

    config_entry.runtime_data.async_set_updated_data(
        PlannerResult(
            state="ok",
            updated=dt_util.utcnow(),
            plan={
                "soc_at_planner_start": 70,
                "charge_to_soc": 60,
                "safe_discharge_soc": 80,
            },
        )
    )
    await hass.async_block_till_done()

    assert hass.states.get(charge_now_entity_id).state == STATE_OFF
    assert hass.states.get(discharge_allowed_entity_id).state == STATE_OFF

    config_entry.runtime_data.async_set_updated_data(
        PlannerResult(
            state="ok",
            updated=dt_util.utcnow(),
            plan={
                "grid_charging_enabled": False,
                "soc_at_planner_start": 40,
                "charge_to_soc": 60,
                "safe_discharge_soc": 30,
            },
        )
    )
    await hass.async_block_till_done()

    assert hass.states.get(charge_now_entity_id).state == STATE_OFF

    config_entry.runtime_data.async_set_updated_data(
        PlannerResult(
            state="insufficient_data",
            updated=dt_util.utcnow(),
            plan={
                "soc_at_planner_start": 70,
                "charge_to_soc": 60,
                "safe_discharge_soc": 80,
            },
        )
    )
    await hass.async_block_till_done()

    assert hass.states.get(charge_now_entity_id).state == STATE_UNAVAILABLE
    assert hass.states.get(discharge_allowed_entity_id).state == STATE_UNAVAILABLE

    config_entry.runtime_data.async_set_updated_data(
        PlannerResult(
            state="ok",
            updated=dt_util.utcnow(),
            plan={"soc_at_planner_start": 70},
        )
    )
    await hass.async_block_till_done()

    assert hass.states.get(charge_now_entity_id).state == STATE_UNAVAILABLE
    assert hass.states.get(discharge_allowed_entity_id).state == STATE_UNAVAILABLE


async def test_runtime_options_are_exposed_as_diagnostic_sensors(hass, config_entry):
    set_source_states(hass)
    config_entry.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, config_entry.entry_id)
    entity_ids = {entity.unique_id: entity.entity_id for entity in entities}

    update_interval = hass.states.get(
        entity_ids[f"{config_entry.entry_id}_{CONF_UPDATE_INTERVAL_MINUTES}"]
    )
    nt_windows = hass.states.get(
        entity_ids[f"{config_entry.entry_id}_{CONF_NT_WINDOWS}"]
    )
    charge_window = hass.states.get(
        entity_ids[f"{config_entry.entry_id}_{CONF_CHARGE_WINDOW}"]
    )

    assert update_interval is not None
    assert update_interval.state == "60"
    assert update_interval.attributes["unit_of_measurement"] == "min"
    assert nt_windows is not None
    assert nt_windows.state == "17:00-19:00,22:00-04:00"
    assert charge_window is not None
    assert charge_window.state == "22:00-04:00"


def test_low_tariff_windows_sensor_reports_disabled():
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={CONF_NT_WINDOWS: []},
    )

    assert _windows_option_value(entry) == "disabled"


def test_charge_window_sensor_reports_disabled():
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={CONF_GRID_CHARGING_ENABLED: False},
    )

    assert _charge_window_option_value(entry) == "disabled"


async def test_history_status_sensor_is_disabled_by_default(hass, config_entry):
    set_source_states(hass)
    config_entry.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity = registry.async_get_entity_id(
        "sensor",
        DOMAIN,
        f"{config_entry.entry_id}_history_status",
    )
    assert entity is not None
    registry_entry = registry.async_get(entity)

    assert registry_entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(entity) is None


async def test_consumption_history_sensor_exposes_hourly_points(hass, config_entry):
    set_source_states(hass)
    config_entry.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED

    hass.states.async_set("sensor.home_energy_total", "1001")
    hass.states.async_set("sensor.ev_energy_total", "200.4")
    hass.states.async_set("sensor.water_heater_energy_total", "50.1")
    await hass.async_block_till_done()

    await config_entry.runtime_data.async_request_refresh()
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor",
        DOMAIN,
        f"{config_entry.entry_id}_consumption_history",
    )
    state = hass.states.get(entity_id)

    assert state is not None
    assert state.attributes["unit_of_measurement"] == "kWh"
    assert round(float(state.state), 6) == 0.5
    assert state.attributes["point_count"] == 1
    assert state.attributes["truncated"] is False
    assert state.attributes["points_compacted"] is True
    point = dict(state.attributes["points"][0])
    timestamp = datetime.fromisoformat(point.pop("timestamp"))
    assert timestamp.minute == 0
    assert timestamp.second == 0
    assert point == {
        "home_kwh": 1.0,
        "managed_kwh": 0.5,
        "base_kwh": 0.5,
        "base_usable": True,
        "is_current_hour": True,
    }


def test_soc_forecast_attributes_stay_under_recorder_limit_with_five_minute_points():
    now = datetime(2026, 7, 5, 16, 30, tzinfo=UTC)
    points = [
        {
            "timestamp": (now + timedelta(minutes=5 * (index + 1))).isoformat(),
            "soc_percent": min(100, 60 + index // 10),
            "battery_kwh": 12.345,
            "solar_kwh": 0.205,
            "consumption_kwh": 0.073,
            "grid_charge_kwh": 0.0,
            "grid_import_kwh": 0.0,
            "unused_surplus_kwh": 0.024,
            "is_nt": index % 2 == 0,
            "is_charge_window": index % 3 == 0,
        }
        for index in range(36 * 12)
    ]
    result = PlannerResult(
        state="ok",
        updated=now,
        plan={
            "soc_forecast": {
                "horizon_hours": 36,
                "source": "ha_entities",
                "points": points,
            },
        },
    )

    attributes = _soc_forecast_attributes(result)

    assert attributes["source_point_count"] == 432
    assert attributes["point_count"] == 144
    assert attributes["points_compacted"] is True
    assert attributes["points_downsampled"] is True
    assert attributes["points_resolution_minutes"] == 15
    assert attributes["points"][0] == {
        "timestamp": "2026-07-05T16:45:00+00:00",
        "soc_percent": 60,
        "unused_surplus_kwh": 0.1,
    }
    assert len(json.dumps(attributes, separators=(",", ":"))) < 16_384


def test_managed_soc_forecast_attributes_include_compact_managed_energy():
    now = datetime(2026, 7, 5, 16, 30, tzinfo=UTC)
    result = PlannerResult(
        state="ok",
        updated=now,
        plan={
            "soc_forecast_with_managed": {
                "horizon_hours": 24,
                "source": "ha_entities_and_managed_estimates",
                "managed_expected_kwh": 2,
                "managed_scheduled_kwh": 2,
                "managed_allocation_by_day": [
                    {
                        "state": "ok",
                        "target_date": "2026-07-06",
                        "available_surplus_kwh": 4,
                        "expected_demand_kwh": 2,
                        "recommended_kwh": 2,
                        "unallocated_surplus_kwh": 2,
                        "warnings": ["omitted from compact attributes"],
                        "loads": {
                            "sensor.boiler": {
                                "load_type": "hot_water",
                                "priority": 10,
                                "state": "ok",
                                "recommended_kwh": 2,
                                "minimum_shortfall_kwh": 0,
                                "average_temperature": 40,
                                "timeline": [
                                    {
                                        "start": "2026-07-06T12:00:00+00:00",
                                        "end": "2026-07-06T13:00:00+00:00",
                                        "mode": "solar",
                                        "energy_kwh": 2,
                                    }
                                ],
                            }
                        },
                    }
                ],
                "points": [
                    {
                        "timestamp": (now + timedelta(minutes=5)).isoformat(),
                        "soc_percent": 70,
                        "unused_surplus_kwh": 0,
                        "managed_consumption_kwh": 0.4,
                    },
                    {
                        "timestamp": (now + timedelta(minutes=10)).isoformat(),
                        "soc_percent": 68,
                        "unused_surplus_kwh": 0,
                        "managed_consumption_kwh": 0.6,
                    },
                    {
                        "timestamp": (now + timedelta(minutes=15)).isoformat(),
                        "soc_percent": 66,
                        "unused_surplus_kwh": 0,
                        "managed_consumption_kwh": 1.0,
                    },
                ],
            }
        },
    )

    attributes = _soc_forecast_with_managed_attributes(result)

    assert attributes["managed_expected_kwh"] == 2
    assert attributes["managed_scheduled_kwh"] == 2
    assert attributes["managed_allocation_by_day"] == [
        {
            "state": "ok",
            "target_date": "2026-07-06",
            "available_surplus_kwh": 4,
            "expected_demand_kwh": 2,
            "recommended_kwh": 2,
            "unallocated_surplus_kwh": 2,
            "loads": {
                "sensor.boiler": {
                    "load_type": "hot_water",
                    "priority": 10,
                    "state": "ok",
                    "recommended_kwh": 2,
                    "minimum_shortfall_kwh": 0,
                }
            },
        }
    ]
    assert attributes["points"] == [
        {
            "timestamp": "2026-07-05T16:45:00+00:00",
            "soc_percent": 66,
            "unused_surplus_kwh": 0.0,
            "managed_consumption_kwh": 2.0,
        }
    ]


def test_consumption_history_attributes_omit_per_source_breakdown():
    result = PlannerResult(
        state="ok",
        updated=datetime(2026, 7, 3, 12, 0),
        forecast={
            "consumption_history": {
                "source": "stored",
                "point_count": 1,
                "points": [
                    {
                        "timestamp": "2026-07-03T11:00:00+02:00",
                        "home_kwh": 1.04,
                        "managed_kwh": 0.55,
                        "managed_sources": {
                            "sensor.ev_energy_total": 0.4,
                            "sensor.water_heater_energy_total": 0.15,
                        },
                        "base_kwh": 0.49,
                        "base_usable": True,
                        "is_current_hour": False,
                    },
                ],
            },
        },
    )

    attributes = _consumption_history_attributes(result)

    assert attributes["points"] == [
        {
            "timestamp": "2026-07-03T11:00:00+02:00",
            "home_kwh": 1.0,
            "managed_kwh": 0.6,
            "base_kwh": 0.5,
            "base_usable": True,
            "is_current_hour": False,
        },
    ]
    assert "managed_sources" not in attributes["points"][0]
    assert attributes["points_compacted"] is True


def test_consumption_history_value_uses_latest_usable_point():
    result = PlannerResult(
        state="ok",
        updated=datetime(2026, 7, 3, 12, 0),
        forecast={
            "consumption_history": {
                "points": [
                    {"base_kwh": 1.4, "base_usable": True},
                    {"base_kwh": 0.0, "base_usable": False},
                ],
            },
        },
    )

    assert _consumption_history_value(result) == 1.4


async def test_managed_source_sensors_expose_per_source_values(hass, config_entry):
    set_source_states(hass)
    config_entry.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED

    hass.states.async_set("sensor.home_energy_total", "1001")
    hass.states.async_set("sensor.ev_energy_total", "200.4")
    hass.states.async_set("sensor.water_heater_energy_total", "50.1")
    await hass.async_block_till_done()

    await config_entry.runtime_data.async_request_refresh()
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    ev_prefix = f"{config_entry.entry_id}_managed_{slugify('sensor.ev_energy_total')}"
    water_prefix = (
        f"{config_entry.entry_id}_managed_{slugify('sensor.water_heater_energy_total')}"
    )

    ev_today = hass.states.get(
        registry.async_get_entity_id("sensor", DOMAIN, f"{ev_prefix}_today")
    )
    ev_current_hour = hass.states.get(
        registry.async_get_entity_id("sensor", DOMAIN, f"{ev_prefix}_current_hour")
    )
    ev_last_hour = hass.states.get(
        registry.async_get_entity_id("sensor", DOMAIN, f"{ev_prefix}_last_hour")
    )
    ev_tracked_total = hass.states.get(
        registry.async_get_entity_id("sensor", DOMAIN, f"{ev_prefix}_tracked_total")
    )
    ev_suggested_entity_id = registry.async_get_entity_id(
        "sensor",
        DOMAIN,
        f"{ev_prefix}_suggested_tomorrow",
    )
    water_today = hass.states.get(
        registry.async_get_entity_id("sensor", DOMAIN, f"{water_prefix}_today")
    )

    assert ev_today is not None
    assert ev_current_hour is not None
    assert ev_last_hour is not None
    assert ev_tracked_total is not None
    assert ev_suggested_entity_id is not None
    assert water_today is not None

    assert round(float(ev_today.state), 6) == 0.4
    assert round(float(ev_current_hour.state), 6) == 0.4
    assert round(float(ev_last_hour.state), 6) == 0.0
    assert round(float(ev_tracked_total.state), 6) == 0.4
    assert round(float(water_today.state), 6) == 0.1

    assert ev_today.attributes["device_class"] == "energy"
    assert ev_today.attributes["state_class"] == "total_increasing"
    assert ev_today.attributes["unit_of_measurement"] == "kWh"
    assert ev_current_hour.attributes["device_class"] == "energy"
    assert "state_class" not in ev_current_hour.attributes
    assert ev_today.attributes["source_entity_id"] == "sensor.ev_energy_total"
    assert ev_today.attributes["source_name"] == "EV charging energy"
    assert ev_today.attributes["point_count"] == 1
    assert "points" not in ev_today.attributes
    assert registry.async_get(ev_suggested_entity_id).config_subentry_id is not None

    config_entry.runtime_data.async_set_updated_data(
        PlannerResult(
            state="ok",
            updated=dt_util.utcnow(),
            plan={
                "surplus_allocation": {
                    "target_date": "2026-08-20",
                    "forecast_complete": True,
                    "available_surplus_kwh": 8.5,
                    "loads": {
                        "sensor.ev_energy_total": {
                            "state": "ok",
                            "load_type": "generic",
                            "priority": 100,
                            "method": "history",
                            "expected_demand_kwh": 6.0,
                            "recommended_kwh": 4.0,
                            "confidence": "medium",
                        }
                    },
                }
            },
        )
    )
    await hass.async_block_till_done()

    ev_suggested = hass.states.get(ev_suggested_entity_id)
    assert ev_suggested is not None
    assert float(ev_suggested.state) == 4
    assert ev_suggested.attributes["method"] == "history"
    assert ev_suggested.attributes["expected_demand_kwh"] == 6

    config_entry.runtime_data.async_set_updated_data(
        PlannerResult(
            state="ok",
            updated=dt_util.utcnow(),
            plan={
                "surplus_allocation": {
                    "target_date": "2026-08-20",
                    "forecast_complete": True,
                    "available_surplus_kwh": 8.5,
                    "loads": {
                        "sensor.ev_energy_total": {
                            "state": "ok",
                            "load_type": "hot_water",
                            "priority": 5,
                            "method": "thermal_model",
                            "average_temperature": 40,
                            "minimum_required_kwh": 1.163,
                            "flexible_capacity_kwh": 5.815,
                            "minimum_shortfall_kwh": 0.163,
                            "recommended_kwh": 1,
                            "planned_target_temperature": 44.3,
                            "timeline": [
                                {
                                    "start": "2026-08-20T12:00:00+02:00",
                                    "end": "2026-08-20T13:00:00+02:00",
                                    "mode": "solar",
                                    "energy_kwh": 1,
                                }
                            ],
                        }
                    },
                }
            },
        )
    )
    await hass.async_block_till_done()

    ev_suggested = hass.states.get(ev_suggested_entity_id)
    assert ev_suggested is not None
    assert float(ev_suggested.state) == 1
    assert ev_suggested.attributes["method"] == "thermal_model"
    assert ev_suggested.attributes["average_temperature"] == 40
    assert ev_suggested.attributes["minimum_required_kwh"] == 1.163
    assert ev_suggested.attributes["flexible_capacity_kwh"] == 5.815
    assert ev_suggested.attributes["minimum_shortfall_kwh"] == 0.163
    assert ev_suggested.attributes["target_date"] == "2026-08-20"
    assert ev_suggested.attributes["forecast_complete"] is True
    assert ev_suggested.attributes["available_surplus_kwh"] == 8.5
    assert ev_suggested.attributes["planned_target_temperature"] == 44.3
    assert ev_suggested.attributes["timeline"] == [
        {
            "start": "2026-08-20T12:00:00+02:00",
            "end": "2026-08-20T13:00:00+02:00",
            "mode": "solar",
            "energy_kwh": 1,
        }
    ]
    assert ev_suggested.state_info is not None
    assert "timeline" in ev_suggested.state_info["unrecorded_attributes"]

    ev_history_entity_id = registry.async_get_entity_id(
        "sensor",
        DOMAIN,
        f"{ev_prefix}_history",
    )
    ev_history_registry_entry = registry.async_get(ev_history_entity_id)
    assert ev_history_registry_entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(ev_history_entity_id) is None


async def test_missing_hot_water_temperature_only_unavailable_suggested_sensor(hass):
    set_source_states(hass)
    temperature_attributes = {
        "device_class": "temperature",
        "unit_of_measurement": "°C",
    }
    hass.states.async_set("sensor.boiler_top", "50", temperature_attributes)
    hass.states.async_set("sensor.boiler_bottom", "unavailable", temperature_attributes)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=config_data(),
        options=options_data(),
        version=3,
        subentries_data=(
            {
                "data": {
                    CONF_MANAGED_ENERGY_ENTITY: "sensor.water_heater_energy_total",
                    CONF_MANAGED_LOAD_TYPE: MANAGED_LOAD_TYPE_HOT_WATER,
                    CONF_PRIORITY: 10,
                    CONF_TOP_TEMPERATURE_ENTITY: "sensor.boiler_top",
                    CONF_BOTTOM_TEMPERATURE_ENTITY: "sensor.boiler_bottom",
                    CONF_MINIMUM_TEMPERATURE_C: 45,
                    CONF_MAXIMUM_TEMPERATURE_C: 70,
                    CONF_TANK_VOLUME_LITERS: 200,
                    CONF_HEATER_POWER_KW: 2,
                    CONF_THERMAL_CONVERSION_FACTOR: 1,
                },
                "subentry_type": MANAGED_LOAD_SUBENTRY,
                "title": "Water heater energy",
                "unique_id": "sensor.water_heater_energy_total",
            },
        ),
    )
    entry.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_managed_{slugify('sensor.water_heater_energy_total')}"
    suggested = hass.states.get(
        registry.async_get_entity_id("sensor", DOMAIN, f"{prefix}_suggested_tomorrow")
    )
    today = hass.states.get(
        registry.async_get_entity_id("sensor", DOMAIN, f"{prefix}_today")
    )

    assert suggested is not None
    assert suggested.state == STATE_UNAVAILABLE
    allocation = entry.runtime_data.data.plan["surplus_allocation"]["loads"][
        "sensor.water_heater_energy_total"
    ]
    assert allocation["load_type"] == "hot_water"
    assert allocation["reason"] == "invalid_temperature_source"
    assert today is not None
    assert today.state != STATE_UNAVAILABLE


async def test_deadline_aware_ev_creates_stable_advisory_sensors(hass):
    set_source_states(hass)
    hass.states.async_set(
        "sensor.enyaq_charge_kwh",
        "4.5",
        {"device_class": "energy_storage", "unit_of_measurement": "kWh"},
    )
    hass.states.async_set("device_tracker.enyaq", "home")
    hass.states.async_set("binary_sensor.enyaq_connected", "off")
    hass.states.async_set("input_boolean.ev_grid_outside_nt", "off")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Energy Planner",
        data=config_data(),
        options=options_data(),
        unique_id=DOMAIN,
        version=5,
        subentries_data=(
            {
                "data": {
                    CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total",
                    CONF_MANAGED_LOAD_TYPE: MANAGED_LOAD_TYPE_ELECTRIC_VEHICLE,
                    CONF_PRIORITY: 10,
                    CONF_REQUIRED_ENERGY_ENTITY: "sensor.enyaq_charge_kwh",
                    CONF_MAXIMUM_CHARGING_POWER_KW: 11,
                    CONF_CHARGING_EFFICIENCY: 0.9,
                    CONF_EV_CHARGING_STRATEGY: (EV_CHARGING_STRATEGY_DEADLINE_AWARE),
                    CONF_EV_PRESENCE_ENTITY: "device_tracker.enyaq",
                    CONF_EV_CONNECTED_ENTITY: "binary_sensor.enyaq_connected",
                    CONF_EV_GRID_OUTSIDE_NT_ENTITY: (
                        "input_boolean.ev_grid_outside_nt"
                    ),
                    CONF_EV_WORKDAYS: [0, 1, 2, 3, 4],
                    CONF_EV_DEPARTURE_TIME: "07:00:00",
                    CONF_EV_RETURN_TIME: "17:00:00",
                },
                "subentry_type": MANAGED_LOAD_SUBENTRY,
                "title": "EV charging energy",
                "unique_id": "sensor.ev_energy_total",
            },
        ),
    )
    entry.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_managed_{slugify('sensor.ev_energy_total')}"
    states = {}
    for description in EV_PLAN_SENSOR_DESCRIPTIONS:
        entity_id = registry.async_get_entity_id(
            SENSOR_DOMAIN,
            DOMAIN,
            f"{prefix}_{description.key}",
        )
        assert entity_id is not None
        states[description.key] = hass.states.get(entity_id)

    assert states["charging_mode"].state == "connect_vehicle"
    assert states["next_departure"].state != STATE_UNAVAILABLE
    planned = states["planned_until_departure"]
    assert planned.state != STATE_UNAVAILABLE
    assert planned.attributes["required_input_kwh"] == 5
    assert planned.attributes["action_window_minutes"] == 60
    assert "solar_kwh" in planned.attributes
    assert "home_battery_kwh" in planned.attributes
    assert "grid_low_tariff_kwh" in planned.attributes
    assert "grid_high_tariff_kwh" in planned.attributes
    assert "shortfall_kwh" in planned.attributes
    assert "solar_if_home_kwh" in planned.attributes
    assert "timeline" in planned.attributes
    assert planned.state_info is not None
    assert "timeline" in planned.state_info["unrecorded_attributes"]


async def test_today_sensors_expose_only_electric_vehicle_recommendations(hass):
    set_source_states(hass)
    hass.states.async_set(
        "sensor.enyaq_charge_kwh",
        "9",
        {"device_class": "energy_storage", "unit_of_measurement": "kWh"},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Energy Planner",
        data=config_data(),
        options=options_data(),
        unique_id=DOMAIN,
        version=4,
        subentries_data=(
            {
                "data": {
                    CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total",
                    CONF_MANAGED_LOAD_TYPE: MANAGED_LOAD_TYPE_ELECTRIC_VEHICLE,
                    CONF_PRIORITY: 10,
                    CONF_REQUIRED_ENERGY_ENTITY: "sensor.enyaq_charge_kwh",
                    CONF_MAXIMUM_CHARGING_POWER_KW: 11,
                    CONF_CHARGING_EFFICIENCY: 0.9,
                },
                "subentry_type": MANAGED_LOAD_SUBENTRY,
                "title": "EV charging energy",
                "unique_id": "sensor.ev_energy_total",
            },
            {
                "data": {
                    CONF_MANAGED_ENERGY_ENTITY: "sensor.water_heater_energy_total",
                    CONF_MANAGED_LOAD_TYPE: MANAGED_LOAD_TYPE_GENERIC,
                    CONF_PRIORITY: 100,
                },
                "subentry_type": MANAGED_LOAD_SUBENTRY,
                "title": "Water heater energy",
                "unique_id": "sensor.water_heater_energy_total",
            },
        ),
    )
    entry.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    ev_prefix = f"{entry.entry_id}_managed_{slugify('sensor.ev_energy_total')}"
    generic_prefix = (
        f"{entry.entry_id}_managed_{slugify('sensor.water_heater_energy_total')}"
    )
    aggregate_entity_id = registry.async_get_entity_id(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_managed_recommended_today_kwh",
    )
    ev_entity_id = registry.async_get_entity_id(
        "sensor",
        DOMAIN,
        f"{ev_prefix}_suggested_today",
    )
    generic_entity_id = registry.async_get_entity_id(
        "sensor",
        DOMAIN,
        f"{generic_prefix}_suggested_today",
    )
    assert aggregate_entity_id == (
        "sensor.energy_planner_recommended_managed_energy_today"
    )
    assert ev_entity_id == (
        "sensor.energy_planner_managed_ev_charging_energy_suggested_today"
    )
    load = {
        "source_entity_id": "sensor.ev_energy_total",
        "load_type": "electric_vehicle",
        "priority": 10,
        "state": "ok",
        "method": "ev_request",
        "battery_required_kwh": 9,
        "electrical_required_kwh": 10,
        "electrical_remaining_before_kwh": 10,
        "electrical_shortfall_kwh": 6.5,
        "battery_shortfall_kwh": 5.85,
        "charging_efficiency": 0.9,
        "maximum_charging_power_kw": 11,
        "recommended_kwh": 3.5,
        "timeline": [
            {
                "start": "2026-08-18T12:00:00+02:00",
                "end": "2026-08-18T13:00:00+02:00",
                "mode": "solar",
                "energy_kwh": 3.5,
            }
        ],
    }
    allocation = {
        "state": "ok",
        "forecast_complete": True,
        "target_date": "2026-08-18",
        "available_surplus_kwh": 3.5,
        "expected_demand_kwh": 10,
        "recommended_kwh": 3.5,
        "unallocated_surplus_kwh": 0,
        "loads": {"sensor.ev_energy_total": load},
    }
    entry.runtime_data.async_set_updated_data(
        PlannerResult(
            state="ok",
            updated=dt_util.utcnow(),
            plan={
                "managed_recommended_today_kwh": 3.5,
                "surplus_allocation_today": allocation,
                "managed_allocation_by_day": [allocation],
            },
        )
    )
    await hass.async_block_till_done()

    aggregate = hass.states.get(aggregate_entity_id)
    ev_today = hass.states.get(ev_entity_id)
    generic_today = hass.states.get(generic_entity_id)
    assert aggregate is not None
    assert float(aggregate.state) == 3.5
    assert (
        aggregate.attributes["managed_allocation_by_day"][0]["loads"][
            "sensor.ev_energy_total"
        ]["battery_shortfall_kwh"]
        == 5.85
    )
    assert ev_today is not None
    assert float(ev_today.state) == 3.5
    assert ev_today.attributes["method"] == "ev_request"
    assert ev_today.attributes["electrical_shortfall_kwh"] == 6.5
    assert ev_today.attributes["battery_shortfall_kwh"] == 5.85
    assert ev_today.attributes["forecast_complete"] is True
    assert ev_today.attributes["target_date"] == "2026-08-18"
    assert ev_today.attributes["timeline"][0]["mode"] == "solar"
    assert generic_today is not None
    assert generic_today.state == STATE_UNAVAILABLE

    entry.runtime_data.async_set_updated_data(
        PlannerResult(
            state="warning",
            updated=dt_util.utcnow(),
            plan={
                "managed_recommended_today_kwh": None,
                "surplus_allocation_today": {
                    **allocation,
                    "state": "insufficient_data",
                    "recommended_kwh": None,
                    "loads": {
                        "sensor.ev_energy_total": {
                            **load,
                            "state": "insufficient_data",
                            "recommended_kwh": None,
                        }
                    },
                },
            },
        )
    )
    await hass.async_block_till_done()
    assert hass.states.get(aggregate_entity_id).state == STATE_UNAVAILABLE
    assert hass.states.get(ev_entity_id).state == STATE_UNAVAILABLE


async def test_sensors_are_unavailable_when_required_data_is_invalid(
    hass,
    config_entry,
):
    set_source_states(hass, invalid_required_state=True)
    config_entry.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED

    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, config_entry.entry_id)
    entity_ids = {entity.unique_id: entity.entity_id for entity in entities}

    planner_state = hass.states.get(entity_ids[f"{config_entry.entry_id}_state"])
    assert planner_state.state == "insufficient_data"

    target_state = hass.states.get(entity_ids[f"{config_entry.entry_id}_target_soc"])
    assert target_state.state == STATE_UNAVAILABLE


async def test_battery_soc_change_requests_debounced_planner_refresh(
    hass,
    config_entry,
    monkeypatch,
):
    monkeypatch.setattr(
        "custom_components.energy_planner.SOC_REFRESH_DEBOUNCE_SECONDS",
        0,
    )
    set_source_states(hass)
    config_entry.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED

    refresh_calls = 0

    async def mock_refresh() -> None:
        nonlocal refresh_calls
        refresh_calls += 1

    config_entry.runtime_data.async_request_refresh = mock_refresh

    hass.states.async_set("sensor.battery_soc", "55")
    await hass.async_block_till_done()
    assert refresh_calls == 0

    hass.states.async_set("sensor.battery_soc", "56")
    hass.states.async_set("sensor.battery_soc", "57")
    for _ in range(3):
        await asyncio.sleep(0)
        await hass.async_block_till_done()
    assert refresh_calls == 1


async def test_energy_source_changes_are_recorded_in_internal_history(
    hass,
    config_entry,
):
    set_source_states(hass)
    config_entry.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED

    hass.states.async_set("sensor.home_energy_total", "1001")
    hass.states.async_set("sensor.ev_energy_total", "200.4")
    hass.states.async_set("sensor.water_heater_energy_total", "50.1")
    await hass.async_block_till_done()

    key = hour_key(
        dt_util.as_local(hass.states.get("sensor.home_energy_total").last_updated)
    )

    assert round(config_entry.runtime_data.history.buckets[key].home_kwh, 6) == 1.0
    assert round(config_entry.runtime_data.history.buckets[key].managed_kwh, 6) == 0.5
    assert {
        source: round(value, 6)
        for source, value in config_entry.runtime_data.history.buckets[
            key
        ].managed_sources.items()
    } == {
        "sensor.ev_energy_total": 0.4,
        "sensor.water_heater_energy_total": 0.1,
    }
    assert (
        round(
            config_entry.runtime_data.history.managed_source_tracked_total_kwh(
                "sensor.ev_energy_total"
            ),
            6,
        )
        == 0.4
    )
    assert (
        round(config_entry.runtime_data.history.base_consumption_for_hour(key), 6)
        == 0.5
    )


async def test_managed_source_changes_request_debounced_planner_refresh(
    hass,
    config_entry,
    monkeypatch,
):
    monkeypatch.setattr(
        "custom_components.energy_planner.MANAGED_SOURCE_REFRESH_DEBOUNCE_SECONDS",
        0,
    )
    set_source_states(hass)
    config_entry.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED

    refresh_calls = 0

    async def mock_refresh() -> None:
        nonlocal refresh_calls
        refresh_calls += 1

    config_entry.runtime_data.async_request_refresh = mock_refresh

    hass.states.async_set("sensor.home_energy_total", "1000.1")
    await hass.async_block_till_done()
    assert refresh_calls == 0

    hass.states.async_set("sensor.ev_energy_total", "200.1")
    hass.states.async_set("sensor.ev_energy_total", "200.2")
    for _ in range(3):
        await asyncio.sleep(0)
        await hass.async_block_till_done()
    assert refresh_calls == 1


async def test_ev_model_input_changes_request_refresh_and_listener_unloads(
    hass,
    monkeypatch,
):
    monkeypatch.setattr(
        "custom_components.energy_planner.EV_MODEL_REFRESH_DEBOUNCE_SECONDS",
        0,
    )
    set_source_states(hass)
    hass.states.async_set(
        "sensor.enyaq_charge_kwh",
        "9",
        {"device_class": "energy_storage", "unit_of_measurement": "kWh"},
    )
    hass.states.async_set("device_tracker.listener_enyaq", "home")
    hass.states.async_set("binary_sensor.listener_enyaq_connected", "on")
    hass.states.async_set("input_boolean.listener_ev_grid_outside_nt", "off")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Energy Planner",
        data=config_data(),
        options=options_data(),
        unique_id=DOMAIN,
        version=5,
        subentries_data=(
            {
                "data": {
                    CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total",
                    CONF_MANAGED_LOAD_TYPE: MANAGED_LOAD_TYPE_ELECTRIC_VEHICLE,
                    CONF_PRIORITY: 10,
                    CONF_REQUIRED_ENERGY_ENTITY: "sensor.enyaq_charge_kwh",
                    CONF_MAXIMUM_CHARGING_POWER_KW: 11,
                    CONF_CHARGING_EFFICIENCY: 0.9,
                    CONF_EV_CHARGING_STRATEGY: (EV_CHARGING_STRATEGY_DEADLINE_AWARE),
                    CONF_EV_PRESENCE_ENTITY: "device_tracker.listener_enyaq",
                    CONF_EV_CONNECTED_ENTITY: (
                        "binary_sensor.listener_enyaq_connected"
                    ),
                    CONF_EV_GRID_OUTSIDE_NT_ENTITY: (
                        "input_boolean.listener_ev_grid_outside_nt"
                    ),
                    CONF_EV_WORKDAYS: [0, 1, 2, 3, 4],
                    CONF_EV_DEPARTURE_TIME: "07:00:00",
                    CONF_EV_RETURN_TIME: "17:00:00",
                },
                "subentry_type": MANAGED_LOAD_SUBENTRY,
                "title": "EV charging energy",
                "unique_id": "sensor.ev_energy_total",
            },
        ),
    )
    entry.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    refresh_calls = 0

    async def mock_refresh() -> None:
        nonlocal refresh_calls
        refresh_calls += 1

    coordinator.async_request_refresh = mock_refresh

    hass.states.async_set("sensor.battery_capacity", "21")
    await hass.async_block_till_done()
    assert refresh_calls == 0

    hass.states.async_set("sensor.enyaq_charge_kwh", "10")
    for _ in range(3):
        await asyncio.sleep(0)
        await hass.async_block_till_done()
    assert refresh_calls == 1

    hass.states.async_set("device_tracker.listener_enyaq", "work")
    for _ in range(3):
        await asyncio.sleep(0)
        await hass.async_block_till_done()
    assert refresh_calls == 2

    hass.states.async_set("binary_sensor.listener_enyaq_connected", "off")
    for _ in range(3):
        await asyncio.sleep(0)
        await hass.async_block_till_done()
    assert refresh_calls == 3

    hass.states.async_set("input_boolean.listener_ev_grid_outside_nt", "on")
    for _ in range(3):
        await asyncio.sleep(0)
        await hass.async_block_till_done()
    assert refresh_calls == 4

    assert await hass.config_entries.async_unload(entry.entry_id)
    hass.states.async_set("sensor.enyaq_charge_kwh", "11")
    hass.states.async_set("device_tracker.listener_enyaq", "home")
    await hass.async_block_till_done()
    assert refresh_calls == 4


async def test_options_update_changes_loaded_recalculation_interval(
    hass,
    config_entry,
):
    set_source_states(hass)
    config_entry.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED

    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, config_entry.entry_id)
    entity_ids = {entity.unique_id: entity.entity_id for entity in entities}
    update_interval_entity_id = entity_ids[
        f"{config_entry.entry_id}_{CONF_UPDATE_INTERVAL_MINUTES}"
    ]

    assert config_entry.runtime_data.update_interval == timedelta(minutes=60)
    assert hass.states.get(update_interval_entity_id).state == "60"

    hass.config_entries.async_update_entry(
        config_entry,
        options={
            **config_entry.options,
            CONF_UPDATE_INTERVAL_MINUTES: 15,
        },
    )
    await hass.async_block_till_done()

    assert config_entry.runtime_data.update_interval == timedelta(minutes=15)
    assert hass.states.get(update_interval_entity_id).state == "15"


async def test_setup_entry_can_be_unloaded(hass, config_entry):
    set_source_states(hass)
    config_entry.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.NOT_LOADED
    assert getattr(config_entry, "runtime_data", None) is None


async def test_remove_entry_removes_internal_history(hass, config_entry):
    history = EnergyHistory()
    history.add_hourly_sample(dt_util.now(), home_kwh=1.0)
    store = EnergyHistoryStore(hass, config_entry.entry_id)
    await store.async_save(history)
    assert (await store.async_load()).buckets

    set_source_states(hass)
    config_entry.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED

    await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()

    assert not (
        await EnergyHistoryStore(hass, config_entry.entry_id).async_load()
    ).buckets
