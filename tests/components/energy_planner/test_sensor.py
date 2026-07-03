from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from custom_components.energy_planner.const import DOMAIN
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
