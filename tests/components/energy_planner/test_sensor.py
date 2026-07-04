from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import EntityCategory
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from custom_components.energy_planner.const import (
    CONF_CHARGE_WINDOW,
    CONF_FORECAST_HORIZON_HOURS,
    CONF_HISTORY_LEARNING_DAYS,
    CONF_NT_WINDOWS,
    CONF_UPDATE_INTERVAL_MINUTES,
    DOMAIN,
)
from custom_components.energy_planner.history import (
    EnergyHistory,
    EnergyHistoryStore,
    hour_key,
)
from custom_components.energy_planner.sensor import SENSOR_DESCRIPTIONS

from .conftest import set_source_states


async def test_setup_entry_creates_all_sensors(hass, config_entry):
    set_source_states(hass)
    config_entry.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED

    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, config_entry.entry_id)
    entity_ids = {entity.unique_id: entity.entity_id for entity in entities}

    assert len(entity_ids) == len(SENSOR_DESCRIPTIONS)

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
    assert categories["soc_forecast_24h"] is None


async def test_only_soc_forecast_uses_battery_device_class(hass, config_entry):
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
    point = dict(state.attributes["points"][0])
    timestamp = datetime.fromisoformat(point.pop("timestamp"))
    assert timestamp.minute == 0
    assert timestamp.second == 0
    assert point == {
        "home_kwh": 1.0,
        "managed_kwh": 0.5,
        "base_kwh": 0.5,
        "is_current_hour": True,
    }


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
    assert (
        round(config_entry.runtime_data.history.base_consumption_for_hour(key), 6)
        == 0.5
    )


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
