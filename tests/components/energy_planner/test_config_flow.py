from __future__ import annotations

from homeassistant import config_entries
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import PERCENTAGE, UnitOfEnergy
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.energy_planner import async_migrate_entry
from custom_components.energy_planner.config_flow import (
    _managed_load_schema,
    _user_schema,
)
from custom_components.energy_planner.const import (
    CONF_BATTERY_CAPACITY_ENTITY,
    CONF_BATTERY_MIN_SOC_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_CHARGE_WINDOW_END,
    CONF_CHARGE_WINDOW_START,
    CONF_FORECAST_HORIZON_HOURS,
    CONF_GRID_CHARGE_EFFICIENCY,
    CONF_GRID_CHARGE_MAX_KW,
    CONF_HISTORY_CORRECTION_PERCENT,
    CONF_HISTORY_LEARNING_DAYS,
    CONF_HOME_ENERGY_ENTITY,
    CONF_INTERVAL_MINUTES,
    CONF_MANAGED_ENERGY_ENTITIES,
    CONF_MANAGED_ENERGY_ENTITY,
    CONF_MIN_BASELINE_KWH_PER_HOUR,
    CONF_NT_WINDOW_1_END,
    CONF_NT_WINDOW_1_START,
    CONF_NT_WINDOW_2_END,
    CONF_NT_WINDOW_2_START,
    CONF_REQUESTED_ENERGY_ENTITY,
    CONF_SOC_EPS_KWH,
    CONF_SOC_RESERVE_PERCENT,
    CONF_SUN_START_REQUIRED_MINUTES,
    CONF_UPDATE_INTERVAL_MINUTES,
    DEFAULT_NAME,
    DOMAIN,
    MANAGED_LOAD_SUBENTRY,
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
    expected_data.pop(CONF_MANAGED_ENERGY_ENTITIES)
    assert result["data"] == expected_data
    assert [subentry["data"] for subentry in result["subentries"]] == [
        {CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total"},
        {CONF_MANAGED_ENERGY_ENTITY: "sensor.water_heater_energy_total"},
    ]
    assert all(
        subentry["subentry_type"] == MANAGED_LOAD_SUBENTRY
        for subentry in result["subentries"]
    )


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
    user_input.pop(CONF_MANAGED_ENERGY_ENTITIES)
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
        version=2,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, MANAGED_LOAD_SUBENTRY),
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total",
            CONF_REQUESTED_ENERGY_ENTITY: "input_number.ev_requested_energy",
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "EV charging energy"
    assert result["data"] == {
        CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total",
        CONF_REQUESTED_ENERGY_ENTITY: "input_number.ev_requested_energy",
    }


async def test_managed_load_subentry_flow_rejects_duplicate_source(hass):
    set_source_states(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        unique_id=DOMAIN,
        version=2,
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
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total"},
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
        version=2,
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
            CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total",
            CONF_REQUESTED_ENERGY_ENTITY: "input_number.ev_requested_energy",
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries[subentry.subentry_id].data == {
        CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total",
        CONF_REQUESTED_ENERGY_ENTITY: "input_number.ev_requested_energy",
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
        version=2,
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, MANAGED_LOAD_SUBENTRY),
        context={"source": config_entries.SOURCE_USER},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total",
            CONF_REQUESTED_ENERGY_ENTITY: "input_number.ev_requested_energy",
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"][CONF_REQUESTED_ENERGY_ENTITY] == "energy_amount_required"


async def test_version_one_entry_migrates_managed_sources_to_subentries(hass):
    set_source_states(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=config_data(),
        unique_id=DOMAIN,
        version=1,
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)

    assert entry.version == 2
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
        for subentry in entry.subentries.values()
    )


async def test_version_one_migration_skips_an_existing_managed_subentry(hass):
    set_source_states(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=config_data(),
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
