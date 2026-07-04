from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.setup import async_setup_component

from custom_components.energy_planner.const import DOMAIN
from custom_components.energy_planner.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import set_source_states


async def test_config_entry_diagnostics_include_compact_summary(hass, config_entry):
    set_source_states(hass)
    config_entry.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED

    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)

    assert diagnostics["entry"]["domain"] == DOMAIN
    assert diagnostics["entry"]["configured_entities"]["battery_soc_entity"]
    assert diagnostics["last_state"] in {"ok", "warning"}
    assert diagnostics["history"]["bucket_count"] >= 0
    assert diagnostics["history"]["learning_days"] == 3
    assert len(diagnostics["entities"]) > 0
    assert "binary_sensor.energy_planner_charge_now" in diagnostics["entities"]
    assert "target_soc" in diagnostics["last_plan"]
