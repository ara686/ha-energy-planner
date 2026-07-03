from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component

from custom_components.energy_planner.const import DOMAIN

from .conftest import set_source_states


async def test_services_raise_when_no_entry_is_loaded(hass):
    assert await async_setup_component(hass, DOMAIN, {})

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, "recalculate", {}, blocking=True)


async def test_services_recalculate_and_export_loaded_entry(hass, config_entry):
    set_source_states(hass)
    config_entry.add_to_hass(hass)
    events = []
    hass.bus.async_listen(f"{DOMAIN}_debug_exported", events.append)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED

    await hass.services.async_call(DOMAIN, "recalculate", {}, blocking=True)
    await hass.services.async_call(DOMAIN, "export_debug", {}, blocking=True)
    await hass.async_block_till_done()

    assert events
    assert config_entry.entry_id in events[-1].data
