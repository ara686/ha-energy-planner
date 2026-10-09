"""Dashboard control of the persistent grid-charging planner option."""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.translation import async_get_translations
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from custom_components.energy_planner.const import (
    CONF_GRID_CHARGING_ENABLED,
    CONF_NOMINAL_POWER_KW,
    CONF_REQUESTED_ENERGY_ENTITY,
    DOMAIN,
)
from custom_components.energy_planner.models import PlannerResult

from .conftest import options_flow_input, set_source_states

ENTITY_ID = "switch.energy_planner_grid_charging_enabled"


async def setup_entry(hass, config_entry):
    set_source_states(hass)
    if hass.config_entries.async_get_entry(config_entry.entry_id) is None:
        config_entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()


async def turn(hass, enabled):
    await hass.services.async_call(
        "switch",
        "turn_on" if enabled else "turn_off",
        {"entity_id": ENTITY_ID},
        blocking=True,
    )
    await hass.async_block_till_done()


@pytest.mark.parametrize("enabled", [None, False, True])
async def test_switch_setup_metadata_and_saved_default(hass, config_entry, enabled):
    options = dict(config_entry.options)
    if enabled is None:
        options.pop(CONF_GRID_CHARGING_ENABLED)
    else:
        options[CONF_GRID_CHARGING_ENABLED] = enabled
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(config_entry, options=options)
    await setup_entry(hass, config_entry)

    state = hass.states.get(ENTITY_ID)
    assert state.state == (STATE_OFF if enabled is False else STATE_ON)
    assert state.name == "Energy Planner Allow battery grid charging during low tariff"
    registered = er.async_get(hass).async_get(ENTITY_ID)
    assert registered.unique_id == (
        f"{config_entry.entry_id}_{CONF_GRID_CHARGING_ENABLED}"
    )
    assert registered.entity_category is EntityCategory.CONFIG
    assert registered.disabled_by is None
    assert registered.config_entry_id == config_entry.entry_id
    device = dr.async_get(hass).async_get(registered.device_id)
    assert (DOMAIN, config_entry.entry_id) in device.identifiers


async def test_switch_preserves_options_reloads_and_survives_setup(
    hass, config_entry, monkeypatch
):
    await setup_entry(hass, config_entry)
    original_options = dict(config_entry.options)
    original_data = dict(config_entry.data)
    original_subentries = dict(config_entry.subentries)
    reload = AsyncMock(wraps=hass.config_entries.async_reload)
    monkeypatch.setattr(hass.config_entries, "async_reload", reload)
    previous_coordinator = config_entry.runtime_data

    await turn(hass, False)
    reload.assert_awaited_once_with(config_entry.entry_id)
    assert config_entry.runtime_data is not previous_coordinator
    assert hass.states.get(ENTITY_ID).state == STATE_OFF
    assert dict(config_entry.options) == {
        **original_options,
        CONF_GRID_CHARGING_ENABLED: False,
    }
    assert dict(config_entry.data) == original_data
    assert dict(config_entry.subentries) == original_subentries

    # A redundant turn-off neither changes options nor schedules a reload.
    reload.reset_mock()
    await turn(hass, False)
    reload.assert_not_awaited()

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert getattr(config_entry, "runtime_data", None) is None
    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_OFF

    await turn(hass, True)
    assert hass.states.get(ENTITY_ID).state == STATE_ON
    assert dict(config_entry.options) == original_options
    reload.reset_mock()
    await turn(hass, True)
    reload.assert_not_awaited()


async def test_switch_and_options_flow_share_the_setting(hass, config_entry):
    await setup_entry(hass, config_entry)
    await turn(hass, False)
    flow = await hass.config_entries.options.async_init(config_entry.entry_id)
    fields = {marker.schema: marker for marker in flow["data_schema"].schema}
    assert fields[CONF_GRID_CHARGING_ENABLED].default() is False

    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], user_input=options_flow_input()
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_ON

    flow = await hass.config_entries.options.async_init(config_entry.entry_id)
    await hass.config_entries.options.async_configure(
        flow["flow_id"],
        user_input=options_flow_input(**{CONF_GRID_CHARGING_ENABLED: False}),
    )
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_OFF


async def test_switch_state_is_independent_of_invalid_planner_data(hass, config_entry):
    await setup_entry(hass, config_entry)
    config_entry.runtime_data.async_set_updated_data(
        PlannerResult(state="insufficient_data", updated=dt_util.utcnow())
    )
    await hass.async_block_till_done()
    assert (
        hass.states.get("sensor.energy_planner_soc_forecast").state == STATE_UNAVAILABLE
    )
    assert hass.states.get(ENTITY_ID).state == STATE_ON


async def test_renamed_switch_keeps_its_identity_after_reload(hass, config_entry):
    await setup_entry(hass, config_entry)
    renamed_id = "switch.my_battery_grid_charging"
    er.async_get(hass).async_update_entity(ENTITY_ID, new_entity_id=renamed_id)
    await hass.async_block_till_done()
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": renamed_id}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID) is None
    assert hass.states.get(renamed_id).state == STATE_OFF


@pytest.mark.parametrize(
    ("language", "name"),
    [
        ("en", "Allow battery grid charging during low tariff"),
        ("cs", "Povolit nabíjení baterie ze sítě v NT"),
        ("sk", "Povoliť nabíjanie batérie zo siete v NT"),
    ],
)
async def test_switch_translations(hass, language, name):
    translations = await async_get_translations(hass, language, "entity", {DOMAIN})
    assert (
        translations[f"component.{DOMAIN}.entity.switch.grid_charging_enabled.name"]
        == name
    )


@pytest.mark.parametrize("mode", ["shadow", "advisory"])
@pytest.mark.parametrize("hour", [22, 1])
async def test_switch_recalculates_all_forecasts_across_midnight(
    hass, config_entry, freezer, mode, hour
):
    freezer.move_to(f"2026-10-09 {hour:02d}:00:00+00:00")
    set_source_states(hass)
    hass.states.async_set("sensor.battery_soc", "20", {"unit_of_measurement": "%"})
    now = dt_util.utcnow()
    hass.states.async_set(
        "sensor.solcast_today",
        "0",
        {
            "detailedForecast": [
                {
                    "period_start": (now + timedelta(hours=i)).isoformat(),
                    "pv_estimate": 3 if 11 <= (now.hour + i) % 24 < 15 else 0,
                    "period_minutes": 60,
                }
                for i in range(48)
            ]
        },
    )
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, options={**config_entry.options, "joint_planning_mode": mode}
    )
    load = next(iter(config_entry.subentries.values()))
    hass.config_entries.async_update_subentry(
        config_entry,
        load,
        data={
            **load.data,
            CONF_REQUESTED_ENERGY_ENTITY: "input_number.managed_energy",
            CONF_NOMINAL_POWER_KW: 1,
        },
    )
    hass.states.async_set(
        "input_number.managed_energy", "2", {"unit_of_measurement": "kWh"}
    )
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert config_entry.runtime_data.data.plan["charged_kwh_total_at_target"] > 0

    await turn(hass, False)
    result = config_entry.runtime_data.data
    assert result.plan[CONF_GRID_CHARGING_ENABLED] is False
    assert result.plan["charged_kwh_total_at_target"] == 0
    assert hass.states.get("binary_sensor.energy_planner_charge_now").state == STATE_OFF
    for key in ("soc_forecast", "soc_forecast_planned", "soc_forecast_with_managed"):
        points = result.plan[key]["points"]
        assert points
        assert all(p["grid_charge_kwh"] == 0 for p in points)
        assert all(p["is_charge_window"] is False for p in points)
        assert any(p["is_nt"] for p in points)
        # The battery still gains energy during forecast solar production.
        assert max(p["soc_percent"] for p in points) > 20
    assert any(
        p.get("managed_consumption_kwh", 0) > 0
        for p in result.plan["soc_forecast_with_managed"]["points"]
    )
    assert result.forecast["points"]
    assert all(p["grid_charge_kwh"] == 0 for p in result.forecast["points"])

    await turn(hass, True)
    result = config_entry.runtime_data.data
    assert result.plan[CONF_GRID_CHARGING_ENABLED] is True
    assert result.plan["charged_kwh_total_at_target"] > 0
    assert any(
        p["grid_charge_kwh"] > 0 for p in result.plan["soc_forecast_planned"]["points"]
    )
