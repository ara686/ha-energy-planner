from __future__ import annotations

from homeassistant import config_entries
from homeassistant.const import UnitOfEnergy
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.energy_planner.config_flow import _user_schema
from custom_components.energy_planner.const import (
    CONF_BATTERY_CAPACITY_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_CHARGE_WINDOW,
    CONF_FORECAST_HORIZON_HOURS,
    CONF_GRID_CHARGE_EFFICIENCY,
    CONF_GRID_CHARGE_MAX_KW,
    CONF_HISTORY_CORRECTION_PERCENT,
    CONF_HISTORY_LEARNING_DAYS,
    CONF_HOME_ENERGY_ENTITY,
    CONF_INTERVAL_MINUTES,
    CONF_MANAGED_ENERGY_ENTITIES,
    CONF_MIN_BASELINE_KWH_PER_HOUR,
    CONF_NT_WINDOWS,
    CONF_SOC_EPS_KWH,
    CONF_SOC_RESERVE_PERCENT,
    CONF_SUN_START_REQUIRED_MINUTES,
    CONF_UPDATE_INTERVAL_MINUTES,
    DEFAULT_NAME,
    DOMAIN,
)

from .conftest import config_data, options_flow_input, set_source_states


async def test_user_flow_creates_entry(hass):
    set_source_states(hass)

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


async def test_user_flow_allows_no_managed_energy_sources(hass):
    set_source_states(hass)
    user_input = config_data()
    user_input.pop(CONF_MANAGED_ENERGY_ENTITIES)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=user_input,
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_MANAGED_ENERGY_ENTITIES not in result["data"]


async def test_user_flow_rejects_battery_capacity_with_current_unit(hass):
    set_source_states(hass)
    hass.states.async_set(
        "sensor.victron_battery_capacity",
        "0.0",
        {"unit_of_measurement": "A"},
    )
    user_input = config_data(
        **{CONF_BATTERY_CAPACITY_ENTITY: "sensor.victron_battery_capacity"}
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=user_input,
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"][CONF_BATTERY_CAPACITY_ENTITY] == "battery_capacity_unit"


async def test_user_flow_rejects_zero_battery_capacity(hass):
    set_source_states(hass)
    hass.states.async_set(
        "sensor.battery_capacity",
        "0",
        {"unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR},
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=config_data(),
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"][CONF_BATTERY_CAPACITY_ENTITY] == "battery_capacity_positive"


async def test_user_flow_rejects_power_sensor_as_home_energy_source(hass):
    set_source_states(hass)
    hass.states.async_set(
        "sensor.home_energy_total",
        "1.2",
        {
            "device_class": "power",
            "state_class": "measurement",
            "unit_of_measurement": "kW",
        },
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=config_data(),
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"][CONF_HOME_ENERGY_ENTITY] == "energy_sensor_required"


async def test_user_flow_rejects_power_sensor_as_managed_energy_source(hass):
    set_source_states(hass)
    hass.states.async_set(
        "sensor.managed_power",
        "800",
        {
            "device_class": "power",
            "state_class": "measurement",
            "unit_of_measurement": "W",
        },
    )
    user_input = config_data(**{CONF_MANAGED_ENERGY_ENTITIES: ["sensor.managed_power"]})

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=user_input,
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"][CONF_MANAGED_ENERGY_ENTITIES] == "energy_sensor_required"


async def test_user_schema_filters_entity_choices_by_expected_type():
    schema = _user_schema()
    fields = {marker.schema: value for marker, value in schema.schema.items()}

    battery_capacity_filter = _plain_filter(
        fields[CONF_BATTERY_CAPACITY_ENTITY].config["filter"]
    )
    home_energy_filter = _plain_filter(fields[CONF_HOME_ENERGY_ENTITY].config["filter"])
    battery_soc_filter = _plain_filter(fields[CONF_BATTERY_SOC_ENTITY].config["filter"])
    managed_energy_config = fields[CONF_MANAGED_ENERGY_ENTITIES].config

    assert {
        "domain": ["sensor"],
        "device_class": ["energy_storage"],
    } in battery_capacity_filter
    assert {
        "domain": ["number"],
        "device_class": ["energy_storage"],
    } in battery_capacity_filter
    assert {"domain": ["input_number"]} in battery_capacity_filter
    assert all("unit_of_measurement" not in item for item in battery_capacity_filter)
    assert home_energy_filter == [{"domain": ["sensor"], "device_class": ["energy"]}]
    assert {
        "domain": ["sensor"],
        "device_class": ["battery"],
    } in battery_soc_filter
    assert {
        "domain": ["number"],
        "device_class": ["battery"],
    } in battery_soc_filter
    assert managed_energy_config["multiple"] is True


def _plain_filter(items):
    return [
        {
            key: [str(item) for item in value]
            if isinstance(value, list)
            else str(value)
            for key, value in item.items()
        }
        for item in items
    ]


async def test_reconfigure_updates_config_entry_entities(hass, config_entry):
    set_source_states(hass)
    hass.states.async_set(
        "sensor.installed_battery_capacity",
        "21.312",
        {"unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR},
    )
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": config_entry.entry_id,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert config_entry.supports_reconfigure

    user_input = config_data(
        **{CONF_BATTERY_CAPACITY_ENTITY: "sensor.installed_battery_capacity"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=user_input,
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert (
        config_entry.data[CONF_BATTERY_CAPACITY_ENTITY]
        == "sensor.installed_battery_capacity"
    )


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
        CONF_UPDATE_INTERVAL_MINUTES: 45,
        CONF_HISTORY_LEARNING_DAYS: 5,
        CONF_INTERVAL_MINUTES: 30,
        CONF_FORECAST_HORIZON_HOURS: 48,
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input=user_input,
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_UPDATE_INTERVAL_MINUTES] == 45
    assert result["data"][CONF_HISTORY_LEARNING_DAYS] == 5
    assert result["data"][CONF_INTERVAL_MINUTES] == 30
    assert result["data"][CONF_FORECAST_HORIZON_HOURS] == 48


async def test_options_flow_schema_accepts_ui_number_values(hass, config_entry):
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    schema = result["data_schema"]

    user_input = {
        CONF_UPDATE_INTERVAL_MINUTES: "60",
        CONF_HISTORY_LEARNING_DAYS: "3",
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

    assert validated[CONF_UPDATE_INTERVAL_MINUTES] == 60.0
    assert validated[CONF_HISTORY_LEARNING_DAYS] == 3.0
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
