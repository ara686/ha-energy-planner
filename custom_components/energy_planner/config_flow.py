from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.number import NumberDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, PERCENTAGE, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector

from .const import (
    CONF_BATTERY_CAPACITY_ENTITY,
    CONF_BATTERY_MIN_SOC_ENTITY,
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
    CONF_PRICE_ENTITY,
    CONF_SOC_EPS_KWH,
    CONF_SOC_RESERVE_PERCENT,
    CONF_SOLCAST_ADDITIONAL_ENTITIES,
    CONF_SOLCAST_TODAY_ENTITY,
    CONF_SOLCAST_TOMORROW_ENTITY,
    CONF_SUN_START_REQUIRED_MINUTES,
    CONF_UPDATE_INTERVAL_MINUTES,
    DEFAULT_NAME,
    DOMAIN,
)
from .options import (
    OptionsValidationError,
    merged_options,
    normalize_options,
    serialize_window,
    serialize_windows,
)
from .sources import parse_float

ERR_BATTERY_CAPACITY_POSITIVE = "battery_capacity_positive"
ERR_BATTERY_CAPACITY_UNIT = "battery_capacity_unit"
ERR_ENERGY_SENSOR_REQUIRED = "energy_sensor_required"
ERR_INVALID_NUMERIC_ENTITY = "invalid_numeric_entity"
ENERGY_STATE_CLASSES = {
    "total",
    "total_increasing",
}

PERCENTAGE_ENTITY_FILTERS: list[selector.EntityFilterSelectorConfig] = [
    {
        "domain": "sensor",
        "device_class": SensorDeviceClass.BATTERY,
        "unit_of_measurement": PERCENTAGE,
    },
    {
        "domain": "number",
        "device_class": NumberDeviceClass.BATTERY,
        "unit_of_measurement": PERCENTAGE,
    },
    {
        "domain": "input_number",
        "unit_of_measurement": PERCENTAGE,
    },
]
BATTERY_CAPACITY_ENTITY_FILTERS: list[selector.EntityFilterSelectorConfig] = [
    {
        "domain": ["sensor", "number", "input_number"],
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
    },
]
ENERGY_SENSOR_FILTERS: list[selector.EntityFilterSelectorConfig] = [
    {
        "domain": "sensor",
        "device_class": SensorDeviceClass.ENERGY,
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
    },
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

    VERSION = 1

    @staticmethod
    def async_get_options_flow(
        config_entry,
    ) -> EnergyPlannerOptionsFlow:
        return EnergyPlannerOptionsFlow(config_entry)

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate_config_input(self.hass, user_input)
            if not errors:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=DEFAULT_NAME, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(),
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
                return self.async_update_reload_and_abort(
                    entry,
                    data=user_input,
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_user_schema(dict(entry.data)),
            errors=errors,
        )


class EnergyPlannerOptionsFlow(config_entries.OptionsFlow):
    """Handle Energy Planner options."""

    def __init__(self, config_entry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                return self.async_create_entry(
                    title="",
                    data=normalize_options(user_input),
                )
            except OptionsValidationError as err:
                errors["base"] = str(err) or "invalid_options"

        options = merged_options(dict(self._config_entry.options))
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
                    CONF_NT_WINDOWS,
                    default=serialize_windows(options[CONF_NT_WINDOWS]),
                ): str,
                vol.Required(
                    CONF_CHARGE_WINDOW,
                    default=serialize_window(options[CONF_CHARGE_WINDOW]),
                ): str,
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
            data_schema=schema,
            errors=errors,
        )


def _user_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            _required(
                CONF_BATTERY_SOC_ENTITY,
                defaults,
            ): _entity_selector(PERCENTAGE_ENTITY_FILTERS),
            _required(
                CONF_BATTERY_CAPACITY_ENTITY,
                defaults,
            ): _entity_selector(BATTERY_CAPACITY_ENTITY_FILTERS),
            _required(
                CONF_BATTERY_MIN_SOC_ENTITY,
                defaults,
            ): _entity_selector(PERCENTAGE_ENTITY_FILTERS),
            _required(
                CONF_HOME_ENERGY_ENTITY,
                defaults,
            ): _entity_selector(ENERGY_SENSOR_FILTERS),
            _optional(
                CONF_MANAGED_ENERGY_ENTITIES,
                defaults,
            ): _entity_selector(ENERGY_SENSOR_FILTERS, multiple=True),
            _optional(
                CONF_SOLCAST_TODAY_ENTITY,
                defaults,
            ): _entity_selector(ENERGY_SENSOR_FILTERS),
            _optional(
                CONF_SOLCAST_TOMORROW_ENTITY,
                defaults,
            ): _entity_selector(ENERGY_SENSOR_FILTERS),
            _optional(
                CONF_SOLCAST_ADDITIONAL_ENTITIES,
                defaults,
            ): _entity_selector(ENERGY_SENSOR_FILTERS, multiple=True),
            _optional(CONF_PRICE_ENTITY, defaults): selector.EntitySelector(
                selector.EntitySelectorConfig(filter={"domain": "sensor"})
            ),
        }
    )


def _required(key: str, defaults: dict[str, Any]) -> vol.Required:
    if key in defaults:
        return vol.Required(key, default=defaults[key])
    return vol.Required(key)


def _optional(key: str, defaults: dict[str, Any]) -> vol.Optional:
    if key in defaults:
        return vol.Optional(key, default=defaults[key])
    return vol.Optional(key)


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
    if multiple:
        config["reorder"] = True
    return selector.EntitySelector(selector.EntitySelectorConfig(**config))


def _validate_config_input(
    hass: HomeAssistant,
    user_input: dict[str, Any],
) -> dict[str, str]:
    errors: dict[str, str] = {}
    _validate_numeric_entity(hass, user_input, CONF_BATTERY_SOC_ENTITY, errors)
    capacity = _validate_numeric_entity(
        hass, user_input, CONF_BATTERY_CAPACITY_ENTITY, errors
    )
    if capacity is not None:
        if not _is_kwh_entity(hass, user_input[CONF_BATTERY_CAPACITY_ENTITY]):
            errors[CONF_BATTERY_CAPACITY_ENTITY] = ERR_BATTERY_CAPACITY_UNIT
        elif capacity <= 0:
            errors[CONF_BATTERY_CAPACITY_ENTITY] = ERR_BATTERY_CAPACITY_POSITIVE
    _validate_numeric_entity(hass, user_input, CONF_BATTERY_MIN_SOC_ENTITY, errors)
    _validate_energy_sensor_entity(
        hass,
        user_input[CONF_HOME_ENERGY_ENTITY],
        CONF_HOME_ENERGY_ENTITY,
        errors,
    )
    for entity_id in _as_entity_list(user_input.get(CONF_MANAGED_ENERGY_ENTITIES)):
        _validate_energy_sensor_entity(
            hass,
            entity_id,
            CONF_MANAGED_ENERGY_ENTITIES,
            errors,
        )
    return errors


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
        _normalize_unit(attributes.get(ATTR_UNIT_OF_MEASUREMENT))
        != _normalize_unit(UnitOfEnergy.KILO_WATT_HOUR)
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
