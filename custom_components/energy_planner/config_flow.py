from __future__ import annotations

import math
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.number import NumberDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    PERCENTAGE,
    UnitOfEnergy,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import (
    CONF_BATTERY_CAPACITY_ENTITY,
    CONF_BATTERY_MIN_SOC_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_BOTTOM_TEMPERATURE_ENTITY,
    CONF_CHARGE_WINDOW,
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
    CONF_SOLCAST_ADDITIONAL_ENTITIES,
    CONF_SOLCAST_TODAY_ENTITY,
    CONF_SOLCAST_TOMORROW_ENTITY,
    CONF_SUN_START_REQUIRED_MINUTES,
    CONF_TANK_VOLUME_LITERS,
    CONF_THERMAL_CONVERSION_FACTOR,
    CONF_TOP_TEMPERATURE_ENTITY,
    CONF_UPDATE_INTERVAL_MINUTES,
    DEFAULT_EV_CHARGING_EFFICIENCY,
    DEFAULT_HOT_WATER_MAXIMUM_TEMPERATURE_C,
    DEFAULT_HOT_WATER_THERMAL_CONVERSION_FACTOR,
    DEFAULT_MANAGED_LOAD_PRIORITY,
    DEFAULT_MANAGED_LOAD_TYPE,
    DEFAULT_NAME,
    DEFAULT_NT_WINDOWS,
    DOMAIN,
    MANAGED_LOAD_SUBENTRY,
    MANAGED_LOAD_TYPE_ELECTRIC_VEHICLE,
    MANAGED_LOAD_TYPE_GENERIC,
    MANAGED_LOAD_TYPE_HOT_WATER,
)
from .options import (
    OptionsValidationError,
    merged_options,
    normalize_options,
)
from .sources import parse_float
from .units import energy_value_to_kwh, is_supported_energy_unit

ERR_BATTERY_CAPACITY_POSITIVE = "battery_capacity_positive"
ERR_BATTERY_CAPACITY_UNIT = "battery_capacity_unit"
ERR_ENERGY_AMOUNT_REQUIRED = "energy_amount_required"
ERR_ENTITY_ALREADY_CONFIGURED = "entity_already_configured"
ERR_ENERGY_SENSOR_REQUIRED = "energy_sensor_required"
ERR_INVALID_NUMERIC_ENTITY = "invalid_numeric_entity"
ERR_PERCENTAGE_ENTITY_REQUIRED = "percentage_entity_required"
ERR_PERCENTAGE_RANGE = "percentage_range"
ERR_POWER_AMOUNT_REQUIRED = "power_amount_required"
ERR_PRIORITY_INVALID = "priority_invalid"
ERR_CHARGING_EFFICIENCY_RANGE = "charging_efficiency_range"
ERR_TEMPERATURE_ENTITIES_DISTINCT = "temperature_entities_distinct"
ERR_TEMPERATURE_RANGE = "temperature_range"
ERR_TEMPERATURE_SENSOR_REQUIRED = "temperature_sensor_required"
ERR_VALUE_POSITIVE = "value_positive"
ENERGY_STATE_CLASSES = {
    "total",
    "total_increasing",
}

BATTERY_SOC_ENTITY_FILTERS: list[selector.EntityFilterSelectorConfig] = [
    {
        "domain": "sensor",
        "device_class": SensorDeviceClass.BATTERY,
    },
    {
        "domain": "number",
        "device_class": NumberDeviceClass.BATTERY,
    },
    {
        "domain": "input_number",
    },
]
BATTERY_MIN_SOC_ENTITY_FILTERS: list[selector.EntityFilterSelectorConfig] = [
    {
        "domain": "sensor",
        "device_class": SensorDeviceClass.BATTERY,
    },
    {
        "domain": "number",
    },
    {
        "domain": "input_number",
    },
]
BATTERY_CAPACITY_ENTITY_FILTERS: list[selector.EntityFilterSelectorConfig] = [
    {
        "domain": "sensor",
        "device_class": SensorDeviceClass.ENERGY_STORAGE,
    },
    {
        "domain": "sensor",
        "device_class": SensorDeviceClass.ENERGY,
    },
    {
        "domain": "number",
        "device_class": NumberDeviceClass.ENERGY_STORAGE,
    },
    {
        "domain": "number",
        "device_class": NumberDeviceClass.ENERGY,
    },
    {
        "domain": "input_number",
    },
]
ENERGY_SENSOR_FILTERS: list[selector.EntityFilterSelectorConfig] = [
    {
        "domain": "sensor",
        "device_class": SensorDeviceClass.ENERGY,
    },
]
SENSOR_ENTITY_FILTERS: list[selector.EntityFilterSelectorConfig] = [
    {
        "domain": "sensor",
    },
]
TEMPERATURE_SENSOR_FILTERS: list[selector.EntityFilterSelectorConfig] = [
    {
        "domain": "sensor",
        "device_class": SensorDeviceClass.TEMPERATURE,
    },
]
REQUESTED_ENERGY_ENTITY_FILTERS: list[selector.EntityFilterSelectorConfig] = [
    {
        "domain": "sensor",
        "device_class": SensorDeviceClass.ENERGY,
    },
    {
        "domain": "sensor",
        "device_class": SensorDeviceClass.ENERGY_STORAGE,
    },
    {
        "domain": "number",
        "device_class": NumberDeviceClass.ENERGY,
    },
    {
        "domain": "number",
        "device_class": NumberDeviceClass.ENERGY_STORAGE,
    },
    {"domain": "input_number"},
]


def _number_selector(
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    step: float | str = "any",
    unit_of_measurement: str | None = None,
) -> selector.NumberSelector:
    config: dict[str, Any] = {
        "mode": selector.NumberSelectorMode.BOX,
        "step": step,
    }
    if minimum is not None:
        config["min"] = minimum
    if maximum is not None:
        config["max"] = maximum
    if unit_of_measurement is not None:
        config["unit_of_measurement"] = unit_of_measurement
    return selector.NumberSelector(selector.NumberSelectorConfig(**config))


class EnergyPlannerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Energy Planner."""

    VERSION = 4

    @staticmethod
    def async_get_options_flow(
        config_entry,
    ) -> EnergyPlannerOptionsFlow:
        return EnergyPlannerOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls,
        config_entry: ConfigEntry,
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return supported managed-load subentry flows."""
        return {MANAGED_LOAD_SUBENTRY: ManagedLoadSubentryFlowHandler}

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate_config_input(self.hass, user_input)
            if not errors:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=DEFAULT_NAME,
                    data=_without_managed_entities(user_input),
                    subentries=[],
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _user_schema(),
                user_input or {},
            ),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input=None):
        """Handle reconfiguration of existing Energy Planner inputs."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate_config_input(self.hass, user_input)
            if not errors:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_mismatch()
                return self.async_update_and_abort(
                    entry,
                    data=_without_managed_entities(user_input),
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                _user_schema(),
                user_input if user_input is not None else dict(entry.data),
            ),
            errors=errors,
        )


class ManagedLoadSubentryFlowHandler(ConfigSubentryFlow):
    """Add or reconfigure one managed load."""

    _selected_load_type: str = DEFAULT_MANAGED_LOAD_TYPE

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> SubentryFlowResult:
        if user_input is not None:
            self._selected_load_type = str(user_input[CONF_MANAGED_LOAD_TYPE])
            return await self._async_step_details()

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _managed_load_type_schema(),
                user_input or {},
            ),
        )

    async def async_step_generic(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Configure a generic managed load."""
        return await self._async_step_details(user_input)

    async def async_step_hot_water(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Configure a hot-water managed load."""
        return await self._async_step_details(user_input)

    async def async_step_electric_vehicle(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Configure an electric-vehicle managed load."""
        return await self._async_step_details(user_input)

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            self._selected_load_type = str(user_input[CONF_MANAGED_LOAD_TYPE])
            return await self._async_step_details(reconfigure=True)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                _managed_load_type_schema(),
                {
                    CONF_MANAGED_LOAD_TYPE: subentry.data.get(
                        CONF_MANAGED_LOAD_TYPE, DEFAULT_MANAGED_LOAD_TYPE
                    ),
                },
            ),
        )

    async def async_step_reconfigure_generic(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Reconfigure a generic managed load."""
        return await self._async_step_details(user_input, reconfigure=True)

    async def async_step_reconfigure_hot_water(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Reconfigure a hot-water managed load."""
        return await self._async_step_details(user_input, reconfigure=True)

    async def async_step_reconfigure_electric_vehicle(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Reconfigure an electric-vehicle managed load."""
        return await self._async_step_details(user_input, reconfigure=True)

    async def _async_step_details(
        self,
        user_input: dict[str, Any] | None = None,
        *,
        reconfigure: bool = False,
    ) -> SubentryFlowResult:
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry() if reconfigure else None
        errors: dict[str, str] = {}
        if user_input is not None:
            complete_input = {
                **user_input,
                CONF_MANAGED_LOAD_TYPE: self._selected_load_type,
            }
            errors = _validate_managed_load_input(
                self.hass,
                entry,
                complete_input,
                current_subentry_id=subentry.subentry_id if subentry else None,
            )
            if not errors:
                source_id = complete_input[CONF_MANAGED_ENERGY_ENTITY]
                data = _clean_managed_load_data(complete_input)
                if subentry is not None:
                    return self.async_update_and_abort(
                        entry,
                        subentry,
                        title=_source_display_name(self.hass, source_id),
                        data=data,
                        unique_id=source_id,
                    )
                return self.async_create_entry(
                    title=_source_display_name(self.hass, source_id),
                    data=data,
                    unique_id=source_id,
                )

        step_id = (
            f"reconfigure_{self._selected_load_type}"
            if reconfigure
            else self._selected_load_type
        )
        suggested = (
            dict(subentry.data) if subentry is not None and user_input is None else {}
        )
        if self._selected_load_type == MANAGED_LOAD_TYPE_ELECTRIC_VEHICLE:
            suggested.setdefault(
                CONF_REQUIRED_ENERGY_ENTITY,
                suggested.get(CONF_REQUESTED_ENERGY_ENTITY),
            )
        elif self._selected_load_type == MANAGED_LOAD_TYPE_GENERIC:
            suggested.setdefault(
                CONF_REQUESTED_ENERGY_ENTITY,
                suggested.get(CONF_REQUIRED_ENERGY_ENTITY),
            )
        suggested = {
            key: value for key, value in suggested.items() if value is not None
        }
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(
                _managed_load_details_schema(self._selected_load_type),
                user_input if user_input is not None else suggested,
            ),
            errors=errors,
        )


class EnergyPlannerOptionsFlow(config_entries.OptionsFlow):
    """Handle Energy Planner options."""

    async def async_step_init(self, user_input=None):
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                return self.async_create_entry(
                    title="",
                    data=normalize_options(user_input),
                )
            except OptionsValidationError as err:
                errors["base"] = err.error_key
            except (TypeError, ValueError):
                errors["base"] = "invalid_options"

        options = merged_options(dict(self.config_entry.options))
        nt_windows = _nt_window_defaults(options)
        nt_windows_enabled = bool(options[CONF_NT_WINDOWS])
        grid_charging_enabled = bool(options[CONF_GRID_CHARGING_ENABLED])
        charge_window = options[CONF_CHARGE_WINDOW]
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_UPDATE_INTERVAL_MINUTES,
                    default=options[CONF_UPDATE_INTERVAL_MINUTES],
                ): _number_selector(
                    minimum=1,
                    step=1,
                    unit_of_measurement="min",
                ),
                vol.Required(
                    CONF_HISTORY_LEARNING_DAYS,
                    default=options[CONF_HISTORY_LEARNING_DAYS],
                ): _number_selector(
                    minimum=1,
                    step=1,
                    unit_of_measurement="d",
                ),
                vol.Required(
                    CONF_INTERVAL_MINUTES,
                    default=options[CONF_INTERVAL_MINUTES],
                ): _number_selector(
                    minimum=1,
                    maximum=60,
                    step=1,
                    unit_of_measurement="min",
                ),
                vol.Required(
                    CONF_HISTORY_CORRECTION_PERCENT,
                    default=options[CONF_HISTORY_CORRECTION_PERCENT],
                ): _number_selector(
                    minimum=-99.999,
                    maximum=500,
                    unit_of_measurement="%",
                ),
                vol.Required(
                    CONF_MIN_BASELINE_KWH_PER_HOUR,
                    default=options[CONF_MIN_BASELINE_KWH_PER_HOUR],
                ): _number_selector(
                    minimum=0,
                    unit_of_measurement="kWh",
                ),
                vol.Required(
                    CONF_GRID_CHARGING_ENABLED,
                    default=grid_charging_enabled,
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_GRID_CHARGE_MAX_KW,
                    default=options[CONF_GRID_CHARGE_MAX_KW],
                ): _number_selector(
                    minimum=0,
                    unit_of_measurement="kW",
                ),
                vol.Required(
                    CONF_GRID_CHARGE_EFFICIENCY,
                    default=options[CONF_GRID_CHARGE_EFFICIENCY],
                ): _number_selector(
                    minimum=0,
                    maximum=1,
                ),
                vol.Required(
                    CONF_SOC_RESERVE_PERCENT,
                    default=options[CONF_SOC_RESERVE_PERCENT],
                ): _number_selector(
                    minimum=0,
                    maximum=100,
                    unit_of_measurement="%",
                ),
                vol.Required(
                    CONF_SOC_EPS_KWH,
                    default=options[CONF_SOC_EPS_KWH],
                ): _number_selector(
                    minimum=0,
                    unit_of_measurement="kWh",
                ),
                vol.Required(
                    CONF_NT_WINDOWS_ENABLED,
                    default=nt_windows_enabled,
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_NT_WINDOW_1_START,
                    default=nt_windows[0]["start"],
                ): _time_selector(),
                vol.Optional(
                    CONF_NT_WINDOW_1_END,
                    default=nt_windows[0]["end"],
                ): _time_selector(),
                vol.Optional(
                    CONF_NT_WINDOW_2_START,
                    default=nt_windows[1]["start"],
                ): _time_selector(),
                vol.Optional(
                    CONF_NT_WINDOW_2_END,
                    default=nt_windows[1]["end"],
                ): _time_selector(),
                vol.Optional(
                    CONF_CHARGE_WINDOW_START,
                    default=charge_window["start"],
                ): _time_selector(),
                vol.Optional(
                    CONF_CHARGE_WINDOW_END,
                    default=charge_window["end"],
                ): _time_selector(),
                vol.Required(
                    CONF_SUN_START_REQUIRED_MINUTES,
                    default=options[CONF_SUN_START_REQUIRED_MINUTES],
                ): _number_selector(
                    minimum=1,
                    step=1,
                    unit_of_measurement="min",
                ),
                vol.Required(
                    CONF_FORECAST_HORIZON_HOURS,
                    default=options[CONF_FORECAST_HORIZON_HOURS],
                ): _number_selector(
                    minimum=24,
                    step=1,
                    unit_of_measurement="h",
                ),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                user_input or {},
            ),
            errors=errors,
        )


def _user_schema() -> vol.Schema:
    fields: dict[vol.Marker, selector.EntitySelector] = {
        vol.Required(CONF_BATTERY_SOC_ENTITY): _entity_selector(
            BATTERY_SOC_ENTITY_FILTERS
        ),
        vol.Required(CONF_BATTERY_CAPACITY_ENTITY): _entity_selector(
            BATTERY_CAPACITY_ENTITY_FILTERS
        ),
        vol.Required(CONF_BATTERY_MIN_SOC_ENTITY): _entity_selector(
            BATTERY_MIN_SOC_ENTITY_FILTERS
        ),
        vol.Required(CONF_HOME_ENERGY_ENTITY): _entity_selector(ENERGY_SENSOR_FILTERS),
        vol.Optional(CONF_SOLCAST_TODAY_ENTITY): _entity_selector(
            SENSOR_ENTITY_FILTERS
        ),
        vol.Optional(CONF_SOLCAST_TOMORROW_ENTITY): _entity_selector(
            SENSOR_ENTITY_FILTERS
        ),
        vol.Optional(CONF_SOLCAST_ADDITIONAL_ENTITIES): _entity_selector(
            SENSOR_ENTITY_FILTERS, multiple=True
        ),
    }
    return vol.Schema(fields)


def _managed_load_type_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_MANAGED_LOAD_TYPE,
                default=DEFAULT_MANAGED_LOAD_TYPE,
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        MANAGED_LOAD_TYPE_GENERIC,
                        MANAGED_LOAD_TYPE_HOT_WATER,
                        MANAGED_LOAD_TYPE_ELECTRIC_VEHICLE,
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    translation_key="managed_load_type",
                )
            )
        }
    )


def _managed_load_details_schema(load_type: str) -> vol.Schema:
    fields: dict[vol.Marker, Any] = {
        vol.Required(CONF_MANAGED_ENERGY_ENTITY): _entity_selector(
            ENERGY_SENSOR_FILTERS
        ),
        vol.Required(
            CONF_PRIORITY,
            default=DEFAULT_MANAGED_LOAD_PRIORITY,
        ): _number_selector(minimum=1, step=1),
    }
    if load_type == MANAGED_LOAD_TYPE_HOT_WATER:
        fields.update(
            {
                vol.Required(CONF_TOP_TEMPERATURE_ENTITY): _entity_selector(
                    TEMPERATURE_SENSOR_FILTERS
                ),
                vol.Required(CONF_BOTTOM_TEMPERATURE_ENTITY): _entity_selector(
                    TEMPERATURE_SENSOR_FILTERS
                ),
                vol.Required(CONF_MINIMUM_TEMPERATURE_C): _number_selector(
                    unit_of_measurement=UnitOfTemperature.CELSIUS
                ),
                vol.Required(
                    CONF_MAXIMUM_TEMPERATURE_C,
                    default=DEFAULT_HOT_WATER_MAXIMUM_TEMPERATURE_C,
                ): _number_selector(unit_of_measurement=UnitOfTemperature.CELSIUS),
                vol.Required(CONF_TANK_VOLUME_LITERS): _number_selector(
                    minimum=0.001,
                    unit_of_measurement="L",
                ),
                vol.Required(CONF_HEATER_POWER_KW): _number_selector(
                    minimum=0.001,
                    unit_of_measurement="kW",
                ),
                vol.Required(
                    CONF_THERMAL_CONVERSION_FACTOR,
                    default=DEFAULT_HOT_WATER_THERMAL_CONVERSION_FACTOR,
                ): _number_selector(minimum=0.001),
            }
        )
    elif load_type == MANAGED_LOAD_TYPE_ELECTRIC_VEHICLE:
        fields.update(
            {
                vol.Required(CONF_REQUIRED_ENERGY_ENTITY): _entity_selector(
                    REQUESTED_ENERGY_ENTITY_FILTERS
                ),
                vol.Required(CONF_MAXIMUM_CHARGING_POWER_KW): _number_selector(
                    minimum=0.001,
                    unit_of_measurement="kW",
                ),
                vol.Required(
                    CONF_CHARGING_EFFICIENCY,
                    default=DEFAULT_EV_CHARGING_EFFICIENCY,
                ): _number_selector(minimum=0.001, maximum=1),
            }
        )
    else:
        fields[vol.Optional(CONF_REQUESTED_ENERGY_ENTITY)] = _entity_selector(
            REQUESTED_ENERGY_ENTITY_FILTERS
        )
    return vol.Schema(fields)


def _managed_load_schema() -> vol.Schema:
    """Return the legacy generic detail schema for compatibility tests."""
    return _managed_load_details_schema(MANAGED_LOAD_TYPE_GENERIC)


def _without_managed_entities(user_input: dict[str, Any]) -> dict[str, Any]:
    """Return main-entry data without the legacy managed-load list."""
    data = dict(user_input)
    data.pop(CONF_MANAGED_ENERGY_ENTITIES, None)
    return data


def _clean_managed_load_data(user_input: dict[str, Any]) -> dict[str, Any]:
    """Normalize persisted managed-load data and remove old type-specific keys."""
    load_type = str(user_input[CONF_MANAGED_LOAD_TYPE])
    data: dict[str, Any] = {
        CONF_MANAGED_ENERGY_ENTITY: str(user_input[CONF_MANAGED_ENERGY_ENTITY]),
        CONF_MANAGED_LOAD_TYPE: load_type,
        CONF_PRIORITY: int(user_input[CONF_PRIORITY]),
    }
    if load_type == MANAGED_LOAD_TYPE_HOT_WATER:
        data.update(
            {
                CONF_TOP_TEMPERATURE_ENTITY: str(
                    user_input[CONF_TOP_TEMPERATURE_ENTITY]
                ),
                CONF_BOTTOM_TEMPERATURE_ENTITY: str(
                    user_input[CONF_BOTTOM_TEMPERATURE_ENTITY]
                ),
                CONF_MINIMUM_TEMPERATURE_C: float(
                    user_input[CONF_MINIMUM_TEMPERATURE_C]
                ),
                CONF_MAXIMUM_TEMPERATURE_C: float(
                    user_input[CONF_MAXIMUM_TEMPERATURE_C]
                ),
                CONF_TANK_VOLUME_LITERS: float(user_input[CONF_TANK_VOLUME_LITERS]),
                CONF_HEATER_POWER_KW: float(user_input[CONF_HEATER_POWER_KW]),
                CONF_THERMAL_CONVERSION_FACTOR: float(
                    user_input[CONF_THERMAL_CONVERSION_FACTOR]
                ),
            }
        )
    elif load_type == MANAGED_LOAD_TYPE_ELECTRIC_VEHICLE:
        data.update(
            {
                CONF_REQUIRED_ENERGY_ENTITY: str(
                    user_input[CONF_REQUIRED_ENERGY_ENTITY]
                ),
                CONF_MAXIMUM_CHARGING_POWER_KW: float(
                    user_input[CONF_MAXIMUM_CHARGING_POWER_KW]
                ),
                CONF_CHARGING_EFFICIENCY: float(user_input[CONF_CHARGING_EFFICIENCY]),
            }
        )
    elif requested_entity_id := user_input.get(CONF_REQUESTED_ENERGY_ENTITY):
        data[CONF_REQUESTED_ENERGY_ENTITY] = str(requested_entity_id)
    return data


def _source_display_name(hass: HomeAssistant, entity_id: str) -> str:
    """Return a human-readable title for one managed load."""
    state = hass.states.get(entity_id)
    return state.name if state is not None else entity_id


def _validate_managed_load_input(
    hass: HomeAssistant,
    entry: ConfigEntry,
    user_input: dict[str, Any],
    *,
    current_subentry_id: str | None = None,
) -> dict[str, str]:
    """Validate common and type-specific managed-load configuration."""
    errors: dict[str, str] = {}
    priority = _finite_float(user_input.get(CONF_PRIORITY))
    if priority is None or priority < 1 or not priority.is_integer():
        errors[CONF_PRIORITY] = ERR_PRIORITY_INVALID
    source_id = str(user_input[CONF_MANAGED_ENERGY_ENTITY])
    _validate_energy_sensor_entity(
        hass,
        source_id,
        CONF_MANAGED_ENERGY_ENTITY,
        errors,
    )
    if any(
        subentry.subentry_id != current_subentry_id
        and subentry.subentry_type == MANAGED_LOAD_SUBENTRY
        and subentry.data.get(CONF_MANAGED_ENERGY_ENTITY) == source_id
        for subentry in entry.subentries.values()
    ):
        errors[CONF_MANAGED_ENERGY_ENTITY] = ERR_ENTITY_ALREADY_CONFIGURED

    load_type = user_input[CONF_MANAGED_LOAD_TYPE]
    if load_type == MANAGED_LOAD_TYPE_HOT_WATER:
        _validate_hot_water_input(hass, user_input, errors)
    elif load_type == MANAGED_LOAD_TYPE_ELECTRIC_VEHICLE:
        _validate_electric_vehicle_input(hass, user_input, errors)
    elif requested_entity_id := user_input.get(CONF_REQUESTED_ENERGY_ENTITY):
        requested_input = {CONF_REQUESTED_ENERGY_ENTITY: requested_entity_id}
        value = _validate_numeric_entity(
            hass,
            requested_input,
            CONF_REQUESTED_ENERGY_ENTITY,
            errors,
        )
        if value is not None and (
            value < 0 or not _is_kwh_entity(hass, str(requested_entity_id))
        ):
            errors[CONF_REQUESTED_ENERGY_ENTITY] = ERR_ENERGY_AMOUNT_REQUIRED
    return errors


def _validate_hot_water_input(
    hass: HomeAssistant,
    user_input: dict[str, Any],
    errors: dict[str, str],
) -> None:
    top_entity = str(user_input[CONF_TOP_TEMPERATURE_ENTITY])
    bottom_entity = str(user_input[CONF_BOTTOM_TEMPERATURE_ENTITY])
    _validate_temperature_entity(hass, top_entity, CONF_TOP_TEMPERATURE_ENTITY, errors)
    _validate_temperature_entity(
        hass, bottom_entity, CONF_BOTTOM_TEMPERATURE_ENTITY, errors
    )
    if top_entity == bottom_entity:
        errors[CONF_BOTTOM_TEMPERATURE_ENTITY] = ERR_TEMPERATURE_ENTITIES_DISTINCT

    minimum = _finite_float(user_input.get(CONF_MINIMUM_TEMPERATURE_C))
    maximum = _finite_float(user_input.get(CONF_MAXIMUM_TEMPERATURE_C))
    if minimum is None or maximum is None or minimum >= maximum:
        errors[CONF_MAXIMUM_TEMPERATURE_C] = ERR_TEMPERATURE_RANGE
    for key in (
        CONF_TANK_VOLUME_LITERS,
        CONF_HEATER_POWER_KW,
        CONF_THERMAL_CONVERSION_FACTOR,
    ):
        value = _finite_float(user_input.get(key))
        if value is None or value <= 0:
            errors[key] = ERR_VALUE_POSITIVE


def _validate_electric_vehicle_input(
    hass: HomeAssistant,
    user_input: dict[str, Any],
    errors: dict[str, str],
) -> None:
    """Validate electric-vehicle energy, power and efficiency inputs."""
    required_entity = str(user_input[CONF_REQUIRED_ENERGY_ENTITY])
    required_state = hass.states.get(required_entity)
    required_value = parse_float(required_state.state if required_state else None)
    if required_value is None or not math.isfinite(required_value):
        errors[CONF_REQUIRED_ENERGY_ENTITY] = ERR_INVALID_NUMERIC_ENTITY
    elif (
        required_state is None
        or required_state.domain not in {"sensor", "number", "input_number"}
        or not _compatible_device_class(
            required_state,
            {SensorDeviceClass.ENERGY, SensorDeviceClass.ENERGY_STORAGE},
        )
        or (
            converted := energy_value_to_kwh(
                required_value,
                required_state.attributes.get(ATTR_UNIT_OF_MEASUREMENT),
            )
        )
        is None
        or converted < 0
    ):
        errors[CONF_REQUIRED_ENERGY_ENTITY] = ERR_ENERGY_AMOUNT_REQUIRED

    maximum_power = _finite_float(user_input.get(CONF_MAXIMUM_CHARGING_POWER_KW))
    if maximum_power is None or maximum_power <= 0:
        errors[CONF_MAXIMUM_CHARGING_POWER_KW] = ERR_POWER_AMOUNT_REQUIRED

    efficiency = _finite_float(user_input.get(CONF_CHARGING_EFFICIENCY))
    if efficiency is None or not 0 < efficiency <= 1:
        errors[CONF_CHARGING_EFFICIENCY] = ERR_CHARGING_EFFICIENCY_RANGE


def _compatible_device_class(state, allowed: set[str]) -> bool:
    """Accept an absent device class or one compatible with the entity amount."""
    device_class = state.attributes.get("device_class")
    return device_class is None or device_class in allowed


def _validate_temperature_entity(
    hass: HomeAssistant,
    entity_id: str,
    key: str,
    errors: dict[str, str],
) -> None:
    state = hass.states.get(entity_id)
    value = parse_float(state.state if state else None)
    if value is None or not math.isfinite(value):
        errors[key] = ERR_INVALID_NUMERIC_ENTITY
        return
    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) if state else None
    if (
        state is None
        or state.domain != "sensor"
        or state.attributes.get("device_class") != SensorDeviceClass.TEMPERATURE
        or unit not in TemperatureConverter.VALID_UNITS
    ):
        errors[key] = ERR_TEMPERATURE_SENSOR_REQUIRED


def _finite_float(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _time_selector() -> selector.TimeSelector:
    return selector.TimeSelector(selector.TimeSelectorConfig())


def _nt_window_defaults(options: dict[str, Any]) -> list[dict[str, str]]:
    windows = options.get(CONF_NT_WINDOWS) or []
    return [
        windows[index] if index < len(windows) else DEFAULT_NT_WINDOWS[index]
        for index in range(2)
    ]


def _entity_selector(
    filters: selector.EntityFilterSelectorConfig
    | list[selector.EntityFilterSelectorConfig],
    *,
    multiple: bool = False,
) -> selector.EntitySelector:
    config: selector.EntitySelectorConfig = {
        "filter": filters,
        "multiple": multiple,
    }
    return selector.EntitySelector(selector.EntitySelectorConfig(**config))


def _validate_config_input(
    hass: HomeAssistant,
    user_input: dict[str, Any],
) -> dict[str, str]:
    errors: dict[str, str] = {}
    _validate_percentage_entity(hass, user_input, CONF_BATTERY_SOC_ENTITY, errors)
    capacity = _validate_numeric_entity(
        hass, user_input, CONF_BATTERY_CAPACITY_ENTITY, errors
    )
    if capacity is not None:
        if not _is_kwh_entity(hass, user_input[CONF_BATTERY_CAPACITY_ENTITY]):
            errors[CONF_BATTERY_CAPACITY_ENTITY] = ERR_BATTERY_CAPACITY_UNIT
        elif capacity <= 0:
            errors[CONF_BATTERY_CAPACITY_ENTITY] = ERR_BATTERY_CAPACITY_POSITIVE
    _validate_percentage_entity(hass, user_input, CONF_BATTERY_MIN_SOC_ENTITY, errors)
    _validate_energy_sensor_entity(
        hass,
        user_input[CONF_HOME_ENERGY_ENTITY],
        CONF_HOME_ENERGY_ENTITY,
        errors,
    )
    return errors


def _validate_percentage_entity(
    hass: HomeAssistant,
    user_input: dict[str, Any],
    key: str,
    errors: dict[str, str],
) -> float | None:
    value = _validate_numeric_entity(hass, user_input, key, errors)
    if value is None:
        return None
    if not 0 <= value <= 100:
        errors[key] = ERR_PERCENTAGE_RANGE
        return value

    state = hass.states.get(user_input[key])
    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) if state else None
    if unit and _normalize_unit(unit) != _normalize_unit(PERCENTAGE):
        errors[key] = ERR_PERCENTAGE_ENTITY_REQUIRED
    return value


def _validate_numeric_entity(
    hass: HomeAssistant,
    user_input: dict[str, Any],
    key: str,
    errors: dict[str, str],
) -> float | None:
    state = hass.states.get(user_input[key])
    value = parse_float(state.state if state else None)
    if value is None:
        errors[key] = ERR_INVALID_NUMERIC_ENTITY
    return value


def _is_kwh_entity(hass: HomeAssistant, entity_id: str) -> bool:
    state = hass.states.get(entity_id)
    if state is None:
        return False
    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
    return _normalize_unit(unit) == _normalize_unit(UnitOfEnergy.KILO_WATT_HOUR)


def _validate_energy_sensor_entity(
    hass: HomeAssistant,
    entity_id: str,
    key: str,
    errors: dict[str, str],
) -> None:
    state = hass.states.get(entity_id)
    value = parse_float(state.state if state else None)
    if value is None:
        errors[key] = ERR_INVALID_NUMERIC_ENTITY
        return
    if not state or state.domain != "sensor":
        errors[key] = ERR_ENERGY_SENSOR_REQUIRED
        return
    attributes = state.attributes
    if (
        not is_supported_energy_unit(attributes.get(ATTR_UNIT_OF_MEASUREMENT))
        or attributes.get("device_class") != SensorDeviceClass.ENERGY
        or attributes.get("state_class") not in ENERGY_STATE_CLASSES
    ):
        errors[key] = ERR_ENERGY_SENSOR_REQUIRED


def _as_entity_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def _normalize_unit(unit: Any) -> str:
    return str(unit or "").replace(" ", "").casefold()
