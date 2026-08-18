from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower, UnitOfTemperature
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.energy_planner import async_migrate_entry
from custom_components.energy_planner.config_flow import (
    _managed_load_details_schema,
    _managed_load_schema,
    _user_schema,
    _validate_managed_load_input,
)
from custom_components.energy_planner.const import (
    CONF_BATTERY_CAPACITY_ENTITY,
    CONF_BATTERY_MIN_SOC_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_BOTTOM_TEMPERATURE_ENTITY,
    CONF_CHARGE_WINDOW_END,
    CONF_CHARGE_WINDOW_START,
    CONF_CHARGING_EFFICIENCY,
    CONF_FORECAST_HORIZON_HOURS,
    CONF_GRID_CHARGE_EFFICIENCY,
    CONF_GRID_CHARGE_MAX_KW,
    CONF_GRID_CHARGING_ENABLED,
    CONF_HEATER_POWER_KW,
    CONF_HISTORY_CORRECTION_PERCENT,
    CONF_HISTORY_LEARNING_DAYS,
    CONF_HOME_ENERGY_ENTITY,
    CONF_INTERVAL_MINUTES,
    CONF_MANAGED_ENERGY_ENTITIES,
    CONF_MANAGED_ENERGY_ENTITY,
    CONF_MANAGED_LOAD_TYPE,
    CONF_MAXIMUM_CHARGING_POWER_ENTITY,
    CONF_MAXIMUM_CHARGING_POWER_KW,
    CONF_MAXIMUM_TEMPERATURE_C,
    CONF_MIN_BASELINE_KWH_PER_HOUR,
    CONF_MINIMUM_TEMPERATURE_C,
    CONF_NT_WINDOW_1_END,
    CONF_NT_WINDOW_1_START,
    CONF_NT_WINDOW_2_END,
    CONF_NT_WINDOW_2_START,
    CONF_NT_WINDOWS,
    CONF_NT_WINDOWS_ENABLED,
    CONF_PRIORITY,
    CONF_REQUESTED_ENERGY_ENTITY,
    CONF_REQUIRED_ENERGY_ENTITY,
    CONF_SOC_EPS_KWH,
    CONF_SOC_RESERVE_PERCENT,
    CONF_SUN_START_REQUIRED_MINUTES,
    CONF_TANK_VOLUME_LITERS,
    CONF_THERMAL_CONVERSION_FACTOR,
    CONF_TOP_TEMPERATURE_ENTITY,
    CONF_UPDATE_INTERVAL_MINUTES,
    DEFAULT_NAME,
    DOMAIN,
    MANAGED_LOAD_SUBENTRY,
    MANAGED_LOAD_TYPE_ELECTRIC_VEHICLE,
    MANAGED_LOAD_TYPE_GENERIC,
    MANAGED_LOAD_TYPE_HOT_WATER,
)
from custom_components.energy_planner.history import EnergyHistory, EnergyHistoryStore

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
    expected_data = config_data()
    assert result["data"] == expected_data
    assert result["subentries"] == ()


async def test_user_flow_allows_no_managed_energy_sources(hass):
    set_source_states(hass)
    user_input = config_data()
    user_input.pop(CONF_MANAGED_ENERGY_ENTITIES, None)

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


async def test_user_flow_accepts_generic_number_for_battery_min_soc(hass):
    set_source_states(hass)
    hass.states.async_set(
        "number.inverter_battery_low_soc",
        "20",
        {"unit_of_measurement": PERCENTAGE},
    )
    user_input = config_data(
        **{
            CONF_BATTERY_MIN_SOC_ENTITY: "number.inverter_battery_low_soc",
        }
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=user_input,
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert (
        result["data"][CONF_BATTERY_MIN_SOC_ENTITY] == "number.inverter_battery_low_soc"
    )


async def test_user_flow_accepts_mwh_home_energy_source(hass):
    set_source_states(hass)
    hass.states.async_set(
        "sensor.inverter_total_load_consumption",
        "12.345",
        {
            "device_class": "energy",
            "state_class": "total_increasing",
            "unit_of_measurement": UnitOfEnergy.MEGA_WATT_HOUR,
        },
    )
    user_input = config_data(
        **{
            CONF_HOME_ENERGY_ENTITY: "sensor.inverter_total_load_consumption",
        }
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=user_input,
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert (
        result["data"][CONF_HOME_ENERGY_ENTITY]
        == "sensor.inverter_total_load_consumption"
    )


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


async def test_user_flow_rejects_soc_outside_percentage_range(hass):
    set_source_states(hass)
    hass.states.async_set(
        "sensor.battery_soc",
        "140",
        {"unit_of_measurement": PERCENTAGE},
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
    assert result["errors"][CONF_BATTERY_SOC_ENTITY] == "percentage_range"


async def test_user_flow_rejects_soc_with_non_percentage_unit(hass):
    set_source_states(hass)
    hass.states.async_set(
        "sensor.battery_min_soc",
        "20",
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
    assert result["errors"][CONF_BATTERY_MIN_SOC_ENTITY] == "percentage_entity_required"


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


async def test_managed_load_flow_rejects_power_sensor_as_energy_source(hass):
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
    entry = MockConfigEntry(domain=DOMAIN, data={}, unique_id=DOMAIN, version=3)
    entry.add_to_hass(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, MANAGED_LOAD_SUBENTRY),
        context={"source": config_entries.SOURCE_USER},
    )
    result = await _select_managed_type(hass, result)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_MANAGED_ENERGY_ENTITY: "sensor.managed_power",
            CONF_PRIORITY: 100,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"][CONF_MANAGED_ENERGY_ENTITY] == "energy_sensor_required"


async def test_user_flow_does_not_offer_untyped_managed_sources(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    fields = {
        marker.schema: value for marker, value in result["data_schema"].schema.items()
    }
    assert CONF_MANAGED_ENERGY_ENTITIES not in fields


async def test_user_schema_filters_entity_choices_by_expected_type():
    schema = _user_schema()
    fields = {marker.schema: value for marker, value in schema.schema.items()}

    battery_capacity_filter = _plain_filter(
        fields[CONF_BATTERY_CAPACITY_ENTITY].config["filter"]
    )
    home_energy_filter = _plain_filter(fields[CONF_HOME_ENERGY_ENTITY].config["filter"])
    battery_soc_filter = _plain_filter(fields[CONF_BATTERY_SOC_ENTITY].config["filter"])
    battery_min_soc_filter = _plain_filter(
        fields[CONF_BATTERY_MIN_SOC_ENTITY].config["filter"]
    )

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
    assert {"domain": ["number"]} not in battery_soc_filter
    assert {"domain": ["number"]} in battery_min_soc_filter
    assert CONF_MANAGED_ENERGY_ENTITIES not in fields


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


def _suggested_values(schema):
    return {
        marker.schema: marker.description["suggested_value"]
        for marker in schema.schema
        if marker.description and "suggested_value" in marker.description
    }


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
    user_input.pop(CONF_MANAGED_ENERGY_ENTITIES, None)
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


async def test_reconfigure_preserves_submitted_values_after_validation_error(
    hass,
    config_entry,
):
    set_source_states(hass)
    hass.states.async_set(
        "sensor.invalid_home_power",
        "1.2",
        {
            "device_class": "power",
            "state_class": "measurement",
            "unit_of_measurement": "kW",
        },
    )
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": config_entry.entry_id,
        },
    )
    user_input = {
        key: value
        for key, value in config_data(
            **{CONF_HOME_ENERGY_ENTITY: "sensor.invalid_home_power"}
        ).items()
        if key != CONF_MANAGED_ENERGY_ENTITIES
    }
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=user_input,
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"][CONF_HOME_ENERGY_ENTITY] == "energy_sensor_required"
    assert _suggested_values(result["data_schema"]) == user_input


async def test_reconfigure_preserves_history_when_energy_sources_change(
    hass,
    config_entry,
):
    set_source_states(hass)
    hass.states.async_set(
        "sensor.new_home_energy_total",
        "2000",
        {
            "device_class": "energy",
            "state_class": "total",
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )
    history = EnergyHistory()
    history.add_hourly_sample(dt_util.now(), home_kwh=1.0)
    store = EnergyHistoryStore(hass, config_entry.entry_id)
    await store.async_save(history)
    assert (await store.async_load()).buckets

    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": config_entry.entry_id,
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            key: value
            for key, value in config_data(
                **{CONF_HOME_ENERGY_ENTITY: "sensor.new_home_energy_total"}
            ).items()
            if key != CONF_MANAGED_ENERGY_ENTITIES
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert (await EnergyHistoryStore(hass, config_entry.entry_id).async_load()).buckets


async def test_managed_load_subentry_flow_accepts_requested_energy(hass):
    set_source_states(hass)
    hass.states.async_set(
        "input_number.ev_requested_energy",
        "8.5",
        {"unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            key: value
            for key, value in config_data().items()
            if key != CONF_MANAGED_ENERGY_ENTITIES
        },
        unique_id=DOMAIN,
        version=3,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, MANAGED_LOAD_SUBENTRY),
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await _select_managed_type(hass, result)

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total",
            CONF_PRIORITY: 100,
            CONF_REQUESTED_ENERGY_ENTITY: "input_number.ev_requested_energy",
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "EV charging energy"
    assert result["data"] == {
        CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total",
        CONF_MANAGED_LOAD_TYPE: MANAGED_LOAD_TYPE_GENERIC,
        CONF_PRIORITY: 100,
        CONF_REQUESTED_ENERGY_ENTITY: "input_number.ev_requested_energy",
    }


async def test_managed_load_subentry_flow_accepts_hot_water_model(hass):
    set_source_states(hass)
    _set_hot_water_temperature_states(hass)
    entry = MockConfigEntry(domain=DOMAIN, data={}, unique_id=DOMAIN, version=3)
    entry.add_to_hass(hass)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, MANAGED_LOAD_SUBENTRY),
        context={"source": config_entries.SOURCE_USER},
    )
    result = await _select_managed_type(
        hass,
        result,
        load_type=MANAGED_LOAD_TYPE_HOT_WATER,
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input=_hot_water_input(priority=5),
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        **_hot_water_input(priority=5),
        CONF_MANAGED_LOAD_TYPE: MANAGED_LOAD_TYPE_HOT_WATER,
    }


async def test_managed_load_subentry_flow_accepts_electric_vehicle_model(hass):
    set_source_states(hass)
    _set_ev_input_states(hass)
    entry = MockConfigEntry(domain=DOMAIN, data={}, unique_id=DOMAIN, version=3)
    entry.add_to_hass(hass)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, MANAGED_LOAD_SUBENTRY),
        context={"source": config_entries.SOURCE_USER},
    )
    result = await _select_managed_type(
        hass,
        result,
        load_type=MANAGED_LOAD_TYPE_ELECTRIC_VEHICLE,
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input=_electric_vehicle_input(priority=5),
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        **_electric_vehicle_input(priority=5),
        CONF_MANAGED_LOAD_TYPE: MANAGED_LOAD_TYPE_ELECTRIC_VEHICLE,
    }


async def test_generic_and_ev_reconfigure_prefills_counterpart_and_cleans_fields(hass):
    set_source_states(hass)
    _set_ev_input_states(hass)
    hass.states.async_set(
        "input_number.ev_requested_energy",
        "7",
        {"unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        unique_id=DOMAIN,
        version=3,
        subentries_data=(
            {
                "data": {
                    CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total",
                    CONF_MANAGED_LOAD_TYPE: MANAGED_LOAD_TYPE_GENERIC,
                    CONF_PRIORITY: 100,
                    CONF_REQUESTED_ENERGY_ENTITY: "input_number.ev_requested_energy",
                },
                "subentry_type": MANAGED_LOAD_SUBENTRY,
                "title": "EV charging energy",
                "unique_id": "sensor.ev_energy_total",
            },
        ),
    )
    entry.add_to_hass(hass)
    subentry = next(iter(entry.subentries.values()))

    result = await entry.start_subentry_reconfigure_flow(hass, subentry.subentry_id)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={CONF_MANAGED_LOAD_TYPE: MANAGED_LOAD_TYPE_ELECTRIC_VEHICLE},
    )
    assert result["step_id"] == "reconfigure_electric_vehicle"
    assert _suggested_values(result["data_schema"])[CONF_REQUIRED_ENERGY_ENTITY] == (
        "input_number.ev_requested_energy"
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            **_electric_vehicle_input(),
            CONF_REQUIRED_ENERGY_ENTITY: "input_number.ev_requested_energy",
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert (
        CONF_REQUESTED_ENERGY_ENTITY not in entry.subentries[subentry.subentry_id].data
    )

    result = await entry.start_subentry_reconfigure_flow(hass, subentry.subentry_id)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={CONF_MANAGED_LOAD_TYPE: MANAGED_LOAD_TYPE_GENERIC},
    )
    assert _suggested_values(result["data_schema"])[CONF_REQUESTED_ENERGY_ENTITY] == (
        "input_number.ev_requested_energy"
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total",
            CONF_PRIORITY: 100,
            CONF_REQUESTED_ENERGY_ENTITY: "input_number.ev_requested_energy",
        },
    )
    assert result["type"] is FlowResultType.ABORT
    updated = entry.subentries[subentry.subentry_id].data
    assert CONF_MAXIMUM_CHARGING_POWER_KW not in updated
    assert CONF_CHARGING_EFFICIENCY not in updated


def test_electric_vehicle_validation_checks_units_values_and_efficiency(hass):
    set_source_states(hass)
    hass.states.async_set(
        "sensor.enyaq_charge_kwh",
        "-1",
        {"device_class": "energy", "unit_of_measurement": "A"},
    )
    user_input = {
        **_electric_vehicle_input(),
        CONF_MANAGED_LOAD_TYPE: MANAGED_LOAD_TYPE_ELECTRIC_VEHICLE,
        CONF_MAXIMUM_CHARGING_POWER_KW: 0,
        CONF_CHARGING_EFFICIENCY: 0,
    }

    errors = _validate_managed_load_input(
        hass,
        MockConfigEntry(domain=DOMAIN, data={}, version=3),
        user_input,
    )

    assert errors[CONF_REQUIRED_ENERGY_ENTITY] == "energy_amount_required"
    assert errors[CONF_MAXIMUM_CHARGING_POWER_KW] == "power_amount_required"
    assert errors[CONF_CHARGING_EFFICIENCY] == "charging_efficiency_range"

    hass.states.async_set(
        "sensor.enyaq_charge_kwh",
        "inf",
        {"device_class": "energy", "unit_of_measurement": "kWh"},
    )
    user_input[CONF_MAXIMUM_CHARGING_POWER_KW] = float("nan")
    errors = _validate_managed_load_input(
        hass,
        MockConfigEntry(domain=DOMAIN, data={}, version=3),
        user_input,
    )
    assert errors[CONF_REQUIRED_ENERGY_ENTITY] == "invalid_numeric_entity"
    assert errors[CONF_MAXIMUM_CHARGING_POWER_KW] == "power_amount_required"


async def test_hot_water_flow_rejects_duplicate_temperature_and_invalid_range(hass):
    set_source_states(hass)
    _set_hot_water_temperature_states(hass)
    entry = MockConfigEntry(domain=DOMAIN, data={}, unique_id=DOMAIN, version=3)
    entry.add_to_hass(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, MANAGED_LOAD_SUBENTRY),
        context={"source": config_entries.SOURCE_USER},
    )
    result = await _select_managed_type(
        hass, result, load_type=MANAGED_LOAD_TYPE_HOT_WATER
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            **_hot_water_input(),
            CONF_BOTTOM_TEMPERATURE_ENTITY: "sensor.boiler_top_temperature",
            CONF_MINIMUM_TEMPERATURE_C: 75,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert (
        result["errors"][CONF_BOTTOM_TEMPERATURE_ENTITY]
        == "temperature_entities_distinct"
    )
    assert result["errors"][CONF_MAXIMUM_TEMPERATURE_C] == "temperature_range"


async def test_managed_load_flow_requires_a_positive_whole_priority(hass):
    set_source_states(hass)
    entry = MockConfigEntry(domain=DOMAIN, data={}, unique_id=DOMAIN, version=3)
    entry.add_to_hass(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, MANAGED_LOAD_SUBENTRY),
        context={"source": config_entries.SOURCE_USER},
    )
    result = await _select_managed_type(hass, result)

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total",
            CONF_PRIORITY: 1.5,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"][CONF_PRIORITY] == "priority_invalid"


def test_hot_water_validation_checks_sensor_metadata_and_positive_parameters(hass):
    set_source_states(hass)
    hass.states.async_set(
        "sensor.boiler_top_temperature",
        "50",
        {"device_class": "humidity", "unit_of_measurement": "°C"},
    )
    hass.states.async_set(
        "sensor.boiler_bottom_temperature",
        "30",
        {"device_class": "temperature", "unit_of_measurement": "V"},
    )
    user_input = {
        **_hot_water_input(),
        CONF_MANAGED_LOAD_TYPE: MANAGED_LOAD_TYPE_HOT_WATER,
        CONF_TANK_VOLUME_LITERS: 0,
        CONF_HEATER_POWER_KW: -1,
        CONF_THERMAL_CONVERSION_FACTOR: float("nan"),
    }

    errors = _validate_managed_load_input(
        hass,
        MockConfigEntry(domain=DOMAIN, data={}, version=3),
        user_input,
    )

    assert errors[CONF_TOP_TEMPERATURE_ENTITY] == "temperature_sensor_required"
    assert errors[CONF_BOTTOM_TEMPERATURE_ENTITY] == "temperature_sensor_required"
    assert errors[CONF_TANK_VOLUME_LITERS] == "value_positive"
    assert errors[CONF_HEATER_POWER_KW] == "value_positive"
    assert errors[CONF_THERMAL_CONVERSION_FACTOR] == "value_positive"

    hass.states.async_set(
        "sensor.boiler_bottom_temperature",
        "unavailable",
        {"device_class": "temperature", "unit_of_measurement": "°C"},
    )
    errors = _validate_managed_load_input(
        hass,
        MockConfigEntry(domain=DOMAIN, data={}, version=3),
        user_input,
    )
    assert errors[CONF_BOTTOM_TEMPERATURE_ENTITY] == "invalid_numeric_entity"


async def test_managed_load_subentry_flow_rejects_duplicate_source(hass):
    set_source_states(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        unique_id=DOMAIN,
        version=3,
        subentries_data=(
            {
                "data": {CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total"},
                "subentry_type": MANAGED_LOAD_SUBENTRY,
                "title": "EV charging energy",
                "unique_id": "sensor.ev_energy_total",
            },
        ),
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, MANAGED_LOAD_SUBENTRY),
        context={"source": config_entries.SOURCE_USER},
    )
    result = await _select_managed_type(hass, result)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total",
            CONF_PRIORITY: 100,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"][CONF_MANAGED_ENERGY_ENTITY] == "entity_already_configured"


async def test_managed_load_subentry_reconfigure_replaces_optional_request(hass):
    set_source_states(hass)
    hass.states.async_set(
        "input_number.ev_requested_energy",
        "7",
        {"unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        unique_id=DOMAIN,
        version=3,
        subentries_data=(
            {
                "data": {CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total"},
                "subentry_type": MANAGED_LOAD_SUBENTRY,
                "title": "EV charging energy",
                "unique_id": "sensor.ev_energy_total",
            },
        ),
    )
    entry.add_to_hass(hass)
    subentry = next(iter(entry.subentries.values()))

    result = await entry.start_subentry_reconfigure_flow(hass, subentry.subentry_id)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_MANAGED_LOAD_TYPE: MANAGED_LOAD_TYPE_GENERIC,
        },
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total",
            CONF_PRIORITY: 25,
            CONF_REQUESTED_ENERGY_ENTITY: "input_number.ev_requested_energy",
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries[subentry.subentry_id].data == {
        CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total",
        CONF_MANAGED_LOAD_TYPE: MANAGED_LOAD_TYPE_GENERIC,
        CONF_PRIORITY: 25,
        CONF_REQUESTED_ENERGY_ENTITY: "input_number.ev_requested_energy",
    }


async def test_managed_load_reconfigure_type_switch_removes_hot_water_fields(hass):
    set_source_states(hass)
    _set_hot_water_temperature_states(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        unique_id=DOMAIN,
        version=3,
        subentries_data=(
            {
                "data": {
                    **_hot_water_input(),
                    CONF_MANAGED_LOAD_TYPE: MANAGED_LOAD_TYPE_HOT_WATER,
                },
                "subentry_type": MANAGED_LOAD_SUBENTRY,
                "title": "Water heater energy",
                "unique_id": "sensor.water_heater_energy_total",
            },
        ),
    )
    entry.add_to_hass(hass)
    subentry = next(iter(entry.subentries.values()))

    result = await entry.start_subentry_reconfigure_flow(hass, subentry.subentry_id)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={CONF_MANAGED_LOAD_TYPE: MANAGED_LOAD_TYPE_GENERIC},
    )
    assert result["step_id"] == "reconfigure_generic"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_MANAGED_ENERGY_ENTITY: "sensor.water_heater_energy_total",
            CONF_PRIORITY: 40,
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert entry.subentries[subentry.subentry_id].data == {
        CONF_MANAGED_ENERGY_ENTITY: "sensor.water_heater_energy_total",
        CONF_MANAGED_LOAD_TYPE: MANAGED_LOAD_TYPE_GENERIC,
        CONF_PRIORITY: 40,
    }


async def test_managed_load_rejects_requested_energy_without_kwh(hass):
    set_source_states(hass)
    hass.states.async_set(
        "input_number.ev_requested_energy",
        "7",
        {"unit_of_measurement": "A"},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        unique_id=DOMAIN,
        version=3,
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, MANAGED_LOAD_SUBENTRY),
        context={"source": config_entries.SOURCE_USER},
    )
    result = await _select_managed_type(hass, result)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total",
            CONF_PRIORITY: 100,
            CONF_REQUESTED_ENERGY_ENTITY: "input_number.ev_requested_energy",
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"][CONF_REQUESTED_ENERGY_ENTITY] == "energy_amount_required"


async def test_version_one_entry_migrates_managed_sources_to_subentries(hass):
    set_source_states(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=config_data(include_managed=True),
        unique_id=DOMAIN,
        version=1,
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)

    assert entry.version == 4
    assert CONF_MANAGED_ENERGY_ENTITIES not in entry.data
    assert {
        subentry.data[CONF_MANAGED_ENERGY_ENTITY]
        for subentry in entry.subentries.values()
    } == {
        "sensor.ev_energy_total",
        "sensor.water_heater_energy_total",
    }
    assert all(
        isinstance(subentry, ConfigSubentry)
        and subentry.subentry_type == MANAGED_LOAD_SUBENTRY
        and subentry.data[CONF_MANAGED_LOAD_TYPE] == MANAGED_LOAD_TYPE_GENERIC
        and subentry.data[CONF_PRIORITY] == 100
        for subentry in entry.subentries.values()
    )


async def test_version_one_migration_skips_an_existing_managed_subentry(hass):
    set_source_states(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=config_data(include_managed=True),
        unique_id=DOMAIN,
        version=1,
        subentries_data=(
            {
                "data": {CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total"},
                "subentry_type": MANAGED_LOAD_SUBENTRY,
                "title": "EV charging energy",
                "unique_id": "sensor.ev_energy_total",
            },
        ),
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)

    assert len(entry.subentries) == 2


async def test_version_two_entry_types_existing_subentries_as_generic(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=config_data(),
        unique_id=DOMAIN,
        version=2,
        subentries_data=(
            {
                "data": {
                    CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total",
                    CONF_REQUESTED_ENERGY_ENTITY: "input_number.ev_requested_energy",
                },
                "subentry_type": MANAGED_LOAD_SUBENTRY,
                "title": "EV charging energy",
                "unique_id": "sensor.ev_energy_total",
            },
        ),
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)

    subentry = next(iter(entry.subentries.values()))
    assert entry.version == 4
    assert subentry.unique_id == "sensor.ev_energy_total"
    assert subentry.data == {
        CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total",
        CONF_REQUESTED_ENERGY_ENTITY: "input_number.ev_requested_energy",
        CONF_MANAGED_LOAD_TYPE: MANAGED_LOAD_TYPE_GENERIC,
        CONF_PRIORITY: 100,
    }


async def test_version_three_entry_migrates_ev_power_entity_to_kw_value(hass):
    hass.states.async_set(
        "number.ev_maximum_charging_power",
        "11000",
        {"device_class": "power", "unit_of_measurement": UnitOfPower.WATT},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=config_data(),
        unique_id=DOMAIN,
        version=3,
        subentries_data=(
            {
                "data": {
                    CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total",
                    CONF_MANAGED_LOAD_TYPE: MANAGED_LOAD_TYPE_ELECTRIC_VEHICLE,
                    CONF_PRIORITY: 100,
                    CONF_REQUIRED_ENERGY_ENTITY: "sensor.enyaq_charge_kwh",
                    CONF_MAXIMUM_CHARGING_POWER_ENTITY: (
                        "number.ev_maximum_charging_power"
                    ),
                    CONF_CHARGING_EFFICIENCY: 0.9,
                },
                "subentry_type": MANAGED_LOAD_SUBENTRY,
                "title": "EV charging energy",
                "unique_id": "sensor.ev_energy_total",
            },
        ),
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)

    subentry = next(iter(entry.subentries.values()))
    assert entry.version == 4
    assert subentry.data[CONF_MAXIMUM_CHARGING_POWER_KW] == 11
    assert CONF_MAXIMUM_CHARGING_POWER_ENTITY not in subentry.data


async def test_version_three_entry_requires_reconfigure_when_power_is_unavailable(
    hass, caplog
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=config_data(),
        unique_id=DOMAIN,
        version=3,
        subentries_data=(
            {
                "data": {
                    CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total",
                    CONF_MANAGED_LOAD_TYPE: MANAGED_LOAD_TYPE_ELECTRIC_VEHICLE,
                    CONF_PRIORITY: 100,
                    CONF_REQUIRED_ENERGY_ENTITY: "sensor.enyaq_charge_kwh",
                    CONF_MAXIMUM_CHARGING_POWER_ENTITY: "number.unavailable_power",
                    CONF_CHARGING_EFFICIENCY: 0.9,
                },
                "subentry_type": MANAGED_LOAD_SUBENTRY,
                "title": "EV charging energy",
                "unique_id": "sensor.ev_energy_total",
            },
        ),
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)

    subentry = next(iter(entry.subentries.values()))
    assert entry.version == 4
    assert CONF_MAXIMUM_CHARGING_POWER_KW not in subentry.data
    assert CONF_MAXIMUM_CHARGING_POWER_ENTITY not in subentry.data
    assert "reconfigure the load" in caplog.text


def test_managed_load_schema_filters_cumulative_and_requested_energy():
    fields = {
        marker.schema: value for marker, value in _managed_load_schema().schema.items()
    }

    managed_filter = _plain_filter(fields[CONF_MANAGED_ENERGY_ENTITY].config["filter"])
    requested_filter = _plain_filter(
        fields[CONF_REQUESTED_ENERGY_ENTITY].config["filter"]
    )

    assert managed_filter == [{"domain": ["sensor"], "device_class": ["energy"]}]
    assert {"domain": ["input_number"]} in requested_filter


def test_hot_water_schema_filters_temperature_entities():
    fields = {
        marker.schema: value
        for marker, value in _managed_load_details_schema(
            MANAGED_LOAD_TYPE_HOT_WATER
        ).schema.items()
    }
    expected = [{"domain": ["sensor"], "device_class": ["temperature"]}]
    assert _plain_filter(fields[CONF_TOP_TEMPERATURE_ENTITY].config["filter"]) == (
        expected
    )
    assert _plain_filter(fields[CONF_BOTTOM_TEMPERATURE_ENTITY].config["filter"]) == (
        expected
    )


def test_electric_vehicle_schema_filters_energy_and_uses_numeric_power():
    fields = {
        marker.schema: value
        for marker, value in _managed_load_details_schema(
            MANAGED_LOAD_TYPE_ELECTRIC_VEHICLE
        ).schema.items()
    }

    required_filter = _plain_filter(
        fields[CONF_REQUIRED_ENERGY_ENTITY].config["filter"]
    )
    power_config = fields[CONF_MAXIMUM_CHARGING_POWER_KW].config
    assert {"domain": ["input_number"]} in required_filter
    assert {"domain": ["sensor"], "device_class": ["energy"]} in required_filter
    assert power_config["min"] == 0.001
    assert power_config["unit_of_measurement"] == "kW"


def _set_hot_water_temperature_states(hass) -> None:
    attributes = {
        "device_class": "temperature",
        "state_class": "measurement",
        "unit_of_measurement": UnitOfTemperature.CELSIUS,
    }
    hass.states.async_set("sensor.boiler_top_temperature", "50", attributes)
    hass.states.async_set("sensor.boiler_bottom_temperature", "30", attributes)


def _hot_water_input(*, priority: int = 100) -> dict:
    return {
        CONF_MANAGED_ENERGY_ENTITY: "sensor.water_heater_energy_total",
        CONF_PRIORITY: priority,
        CONF_TOP_TEMPERATURE_ENTITY: "sensor.boiler_top_temperature",
        CONF_BOTTOM_TEMPERATURE_ENTITY: "sensor.boiler_bottom_temperature",
        CONF_MINIMUM_TEMPERATURE_C: 45.0,
        CONF_MAXIMUM_TEMPERATURE_C: 70.0,
        CONF_TANK_VOLUME_LITERS: 200.0,
        CONF_HEATER_POWER_KW: 2.0,
        CONF_THERMAL_CONVERSION_FACTOR: 1.0,
    }


def _set_ev_input_states(hass) -> None:
    hass.states.async_set(
        "sensor.enyaq_charge_kwh",
        "18000",
        {
            "device_class": "energy_storage",
            "state_class": "measurement",
            "unit_of_measurement": UnitOfEnergy.WATT_HOUR,
        },
    )


def _electric_vehicle_input(*, priority: int = 100) -> dict:
    return {
        CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total",
        CONF_PRIORITY: priority,
        CONF_REQUIRED_ENERGY_ENTITY: "sensor.enyaq_charge_kwh",
        CONF_MAXIMUM_CHARGING_POWER_KW: 11.0,
        CONF_CHARGING_EFFICIENCY: 0.9,
    }


async def _select_managed_type(
    hass,
    result,
    *,
    load_type: str = MANAGED_LOAD_TYPE_GENERIC,
):
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_MANAGED_LOAD_TYPE: load_type,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == load_type
    return result


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


async def test_options_flow_can_disable_low_tariff_windows(hass, config_entry):
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    fields = {marker.schema: marker for marker in result["data_schema"].schema}

    assert isinstance(fields[CONF_NT_WINDOW_1_START], vol.Optional)
    assert isinstance(fields[CONF_NT_WINDOW_1_END], vol.Optional)
    assert isinstance(fields[CONF_NT_WINDOW_2_START], vol.Optional)
    assert isinstance(fields[CONF_NT_WINDOW_2_END], vol.Optional)

    user_input = {
        **options_flow_input(),
        CONF_NT_WINDOWS_ENABLED: False,
        CONF_NT_WINDOW_1_START: "00:00",
        CONF_NT_WINDOW_1_END: "00:00",
        CONF_NT_WINDOW_2_START: "00:00",
        CONF_NT_WINDOW_2_END: "00:00",
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input=user_input,
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_NT_WINDOWS] == []


async def test_options_flow_can_disable_grid_charging_planning(hass, config_entry):
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    fields = {marker.schema: marker for marker in result["data_schema"].schema}

    assert isinstance(fields[CONF_CHARGE_WINDOW_START], vol.Optional)
    assert isinstance(fields[CONF_CHARGE_WINDOW_END], vol.Optional)

    user_input = {
        **options_flow_input(),
        CONF_GRID_CHARGING_ENABLED: False,
        CONF_CHARGE_WINDOW_START: "00:00",
        CONF_CHARGE_WINDOW_END: "00:00",
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input=user_input,
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_GRID_CHARGING_ENABLED] is False


async def test_options_flow_preserves_disabled_choices_after_error(
    hass,
    config_entry,
):
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    user_input = {
        **options_flow_input(),
        CONF_INTERVAL_MINUTES: 7,
        CONF_GRID_CHARGING_ENABLED: False,
        CONF_NT_WINDOWS_ENABLED: False,
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input=user_input,
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == CONF_INTERVAL_MINUTES
    assert _suggested_values(result["data_schema"]) == user_input


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
        CONF_GRID_CHARGING_ENABLED: True,
        CONF_GRID_CHARGE_MAX_KW: "5.5",
        CONF_GRID_CHARGE_EFFICIENCY: "0.92",
        CONF_SOC_RESERVE_PERCENT: 1,
        CONF_SOC_EPS_KWH: "0.02",
        CONF_NT_WINDOW_1_START: "17:00",
        CONF_NT_WINDOW_1_END: "19:00",
        CONF_NT_WINDOW_2_START: "22:00",
        CONF_NT_WINDOW_2_END: "04:00",
        CONF_CHARGE_WINDOW_START: "22:00",
        CONF_CHARGE_WINDOW_END: "04:00",
        CONF_SUN_START_REQUIRED_MINUTES: "30",
        CONF_FORECAST_HORIZON_HOURS: "48",
    }

    validated = schema(user_input)

    assert validated[CONF_UPDATE_INTERVAL_MINUTES] == 60.0
    assert validated[CONF_HISTORY_LEARNING_DAYS] == 3.0
    assert validated[CONF_SOC_RESERVE_PERCENT] == 1.0
    assert validated[CONF_HISTORY_CORRECTION_PERCENT] == 5.0
    assert validated[CONF_INTERVAL_MINUTES] == 30.0
    assert validated[CONF_NT_WINDOW_1_START] == "17:00"


async def test_options_flow_rejects_invalid_values(hass, config_entry):
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={**options_flow_input(), CONF_INTERVAL_MINUTES: 7},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == CONF_INTERVAL_MINUTES
