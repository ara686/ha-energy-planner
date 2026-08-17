from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.energy_planner.const import (
    CONF_BOTTOM_TEMPERATURE_ENTITY,
    CONF_HEATER_POWER_KW,
    CONF_MANAGED_ENERGY_ENTITY,
    CONF_MANAGED_LOAD_TYPE,
    CONF_MAXIMUM_TEMPERATURE_C,
    CONF_MINIMUM_TEMPERATURE_C,
    CONF_PRIORITY,
    CONF_TANK_VOLUME_LITERS,
    CONF_THERMAL_CONVERSION_FACTOR,
    CONF_TOP_TEMPERATURE_ENTITY,
    DOMAIN,
    MANAGED_LOAD_SUBENTRY,
    MANAGED_LOAD_TYPE_HOT_WATER,
)
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
    assert {
        load["source_entity_id"] for load in diagnostics["entry"]["managed_loads"]
    } == {
        "sensor.ev_energy_total",
        "sensor.water_heater_energy_total",
    }
    assert diagnostics["last_state"] in {"ok", "warning"}
    assert diagnostics["history"]["bucket_count"] >= 0
    assert diagnostics["history"]["learning_days"] == 3
    assert len(diagnostics["entities"]) > 0
    assert "binary_sensor.energy_planner_charge_now" in diagnostics["entities"]
    assert "target_soc" in diagnostics["last_plan"]


async def test_diagnostics_include_hot_water_model_configuration(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        version=3,
        subentries_data=(
            {
                "data": {
                    CONF_MANAGED_ENERGY_ENTITY: "sensor.boiler_energy_total",
                    CONF_MANAGED_LOAD_TYPE: MANAGED_LOAD_TYPE_HOT_WATER,
                    CONF_PRIORITY: 5,
                    CONF_TOP_TEMPERATURE_ENTITY: "sensor.boiler_top",
                    CONF_BOTTOM_TEMPERATURE_ENTITY: "sensor.boiler_bottom",
                    CONF_MINIMUM_TEMPERATURE_C: 45,
                    CONF_MAXIMUM_TEMPERATURE_C: 70,
                    CONF_TANK_VOLUME_LITERS: 200,
                    CONF_HEATER_POWER_KW: 2,
                    CONF_THERMAL_CONVERSION_FACTOR: 1,
                },
                "subentry_type": MANAGED_LOAD_SUBENTRY,
                "title": "Boiler",
                "unique_id": "sensor.boiler_energy_total",
            },
        ),
    )
    entry.add_to_hass(hass)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["entry"]["managed_loads"] == [
        {
            "source_entity_id": "sensor.boiler_energy_total",
            "load_type": "hot_water",
            "priority": 5,
            "requested_energy_entity_id": None,
            "top_temperature_entity_id": "sensor.boiler_top",
            "bottom_temperature_entity_id": "sensor.boiler_bottom",
            "minimum_temperature_c": 45.0,
            "maximum_temperature_c": 70.0,
            "tank_volume_liters": 200.0,
            "heater_power_kw": 2.0,
            "thermal_conversion_factor": 1.0,
        }
    ]
