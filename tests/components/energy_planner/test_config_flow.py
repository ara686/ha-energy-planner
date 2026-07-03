from __future__ import annotations

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.energy_planner.const import (
    CONF_CHARGE_WINDOW,
    CONF_FORECAST_HORIZON_HOURS,
    CONF_GRID_CHARGE_EFFICIENCY,
    CONF_GRID_CHARGE_MAX_KW,
    CONF_HISTORY_CORRECTION_PERCENT,
    CONF_INTERVAL_MINUTES,
    CONF_MIN_BASELINE_KWH_PER_HOUR,
    CONF_NT_WINDOWS,
    CONF_SOC_EPS_KWH,
    CONF_SOC_RESERVE_PERCENT,
    CONF_SUN_START_REQUIRED_MINUTES,
    DEFAULT_NAME,
    DOMAIN,
)

from .conftest import config_data, options_flow_input


async def test_user_flow_creates_entry(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=config_data(),
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == DEFAULT_NAME
    assert result["data"] == config_data()


async def test_user_flow_blocks_duplicate_entry(hass):
    MockConfigEntry(
        domain=DOMAIN,
        data=config_data(),
        unique_id=DOMAIN,
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data=config_data(),
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_options_flow_updates_runtime_options(hass, config_entry):
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    user_input = {
        **options_flow_input(),
        CONF_INTERVAL_MINUTES: 30,
        CONF_FORECAST_HORIZON_HOURS: 48,
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input=user_input,
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_INTERVAL_MINUTES] == 30
    assert result["data"][CONF_FORECAST_HORIZON_HOURS] == 48


async def test_options_flow_schema_accepts_ui_number_values(hass, config_entry):
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    schema = result["data_schema"]

    user_input = {
        CONF_INTERVAL_MINUTES: "30",
        CONF_HISTORY_CORRECTION_PERCENT: "5.0",
        CONF_MIN_BASELINE_KWH_PER_HOUR: "0.2",
        CONF_GRID_CHARGE_MAX_KW: "5.5",
        CONF_GRID_CHARGE_EFFICIENCY: "0.92",
        CONF_SOC_RESERVE_PERCENT: 1,
        CONF_SOC_EPS_KWH: "0.02",
        CONF_NT_WINDOWS: "17:00-19:00,22:00-04:00",
        CONF_CHARGE_WINDOW: "22:00-04:00",
        CONF_SUN_START_REQUIRED_MINUTES: "30",
        CONF_FORECAST_HORIZON_HOURS: "48",
    }

    validated = schema(user_input)

    assert validated[CONF_SOC_RESERVE_PERCENT] == 1.0
    assert validated[CONF_HISTORY_CORRECTION_PERCENT] == 5.0
    assert validated[CONF_INTERVAL_MINUTES] == 30.0


async def test_options_flow_rejects_invalid_values(hass, config_entry):
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={**options_flow_input(), CONF_INTERVAL_MINUTES: 7},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == CONF_INTERVAL_MINUTES
