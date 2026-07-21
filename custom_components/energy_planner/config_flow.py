from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.number import NumberDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigSubentryData,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, PERCENTAGE, UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_BATTERY_CAPACITY_ENTITY,
    CONF_BATTERY_MIN_SOC_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_CHARGE_WINDOW,
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
    CONF_NT_WINDOWS,
    CONF_REQUESTED_ENERGY_ENTITY,
    CONF_SOC_EPS_KWH,
    CONF_SOC_RESERVE_PERCENT,
    CONF_SOLCAST_ADDITIONAL_ENTITIES,
    CONF_SOLCAST_TODAY_ENTITY,
    CONF_SOLCAST_TOMORROW_ENTITY,
    CONF_SUN_START_REQUIRED_MINUTES,
    CONF_UPDATE_INTERVAL_MINUTES,
    DEFAULT_NAME,
    DEFAULT_NT_WINDOWS,
    DOMAIN,
    MANAGED_LOAD_SUBENTRY,
)
from .options import (
    OptionsValidationError,
    merged_options,
    normalize_options,
)
from .sources import parse_float

ERR_BATTERY_CAPACITY_POSITIVE = "battery_capacity_positive"
ERR_BATTERY_CAPACITY_UNIT = "battery_capacity_unit"
ERR_ENERGY_AMOUNT_REQUIRED = "energy_amount_required"
ERR_ENTITY_ALREADY_CONFIGURED = "entity_already_configured"
ERR_ENERGY_SENSOR_REQUIRED = "energy_sensor_required"
ERR_INVALID_NUMERIC_ENTITY = "invalid_numeric_entity"
ERR_PERCENTAGE_ENTITY_REQUIRED = "percentage_entity_required"
ERR_PERCENTAGE_RANGE = "percentage_range"
ENERGY_STATE_CLASSES = {
    "total",
    "total_increasing",
}

PERCENTAGE_ENTITY_FILTERS: list[selector.EntityFilterSelectorConfig] = [
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

    VERSION = 2

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
                    subentries=_managed_load_subentries(self.hass, user_input),
                )

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
                return self.async_update_and_abort(
                    entry,
                    data=_without_managed_entities(user_input),
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_user_schema(dict(entry.data), include_managed=False),
            errors=errors,
        )


class ManagedLoadSubentryFlowHandler(ConfigSubentryFlow):
    """Add or reconfigure one managed load."""

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_managed_load_input(
                self.hass,
                self._get_entry(),
                user_input,
            )
            if not errors:
                source_id = user_input[CONF_MANAGED_ENERGY_ENTITY]
                return self.async_create_entry(
                    title=_source_display_name(self.hass, source_id),
                    data=_clean_managed_load_data(user_input),
                    unique_id=source_id,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_managed_load_schema(),
            errors=errors,
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> SubentryFlowResult:
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_managed_load_input(
                self.hass,
                entry,
                user_input,
                current_subentry_id=subentry.subentry_id,
            )
            if not errors:
                source_id = user_input[CONF_MANAGED_ENERGY_ENTITY]
                return self.async_update_and_abort(
                    entry,
                    subentry,
                    title=_source_display_name(self.hass, source_id),
                    data=_clean_managed_load_data(user_input),
                    unique_id=source_id,
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_managed_load_schema(dict(subentry.data)),
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
                    CONF_NT_WINDOW_1_START,
                    default=nt_windows[0]["start"],
                ): _time_selector(),
                vol.Required(
                    CONF_NT_WINDOW_1_END,
                    default=nt_windows[0]["end"],
                ): _time_selector(),
                vol.Required(
                    CONF_NT_WINDOW_2_START,
                    default=nt_windows[1]["start"],
                ): _time_selector(),
                vol.Required(
                    CONF_NT_WINDOW_2_END,
                    default=nt_windows[1]["end"],
                ): _time_selector(),
                vol.Required(
                    CONF_CHARGE_WINDOW_START,
                    default=charge_window["start"],
                ): _time_selector(),
                vol.Required(
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
            data_schema=schema,
            errors=errors,
        )


def _user_schema(
    defaults: dict[str, Any] | None = None,
    *,
    include_managed: bool = True,
) -> vol.Schema:
    defaults = defaults or {}
    fields: dict[vol.Marker, selector.EntitySelector] = {
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
            CONF_SOLCAST_TODAY_ENTITY,
            defaults,
        ): _entity_selector(SENSOR_ENTITY_FILTERS),
        _optional(
            CONF_SOLCAST_TOMORROW_ENTITY,
            defaults,
        ): _entity_selector(SENSOR_ENTITY_FILTERS),
        _optional(
            CONF_SOLCAST_ADDITIONAL_ENTITIES,
            defaults,
        ): _entity_selector(SENSOR_ENTITY_FILTERS, multiple=True),
    }
    if include_managed:
        fields[
            _optional(
                CONF_MANAGED_ENERGY_ENTITIES,
                defaults,
            )
        ] = _entity_selector(ENERGY_SENSOR_FILTERS, multiple=True)
    return vol.Schema(fields)


def _managed_load_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            _required(
                CONF_MANAGED_ENERGY_ENTITY,
                defaults,
            ): _entity_selector(ENERGY_SENSOR_FILTERS),
            _optional(
                CONF_REQUESTED_ENERGY_ENTITY,
                defaults,
            ): _entity_selector(REQUESTED_ENERGY_ENTITY_FILTERS),
        }
    )


def _without_managed_entities(user_input: dict[str, Any]) -> dict[str, Any]:
    """Return main-entry data without the legacy managed-load list."""
    data = dict(user_input)
    data.pop(CONF_MANAGED_ENERGY_ENTITIES, None)
    return data


def _managed_load_subentries(
    hass: HomeAssistant,
    user_input: dict[str, Any],
) -> list[ConfigSubentryData]:
    """Convert managed entities selected during initial setup to subentries."""
    return [
        ConfigSubentryData(
            data={CONF_MANAGED_ENERGY_ENTITY: entity_id},
            subentry_type=MANAGED_LOAD_SUBENTRY,
            title=_source_display_name(hass, entity_id),
            unique_id=entity_id,
        )
        for entity_id in dict.fromkeys(
            _as_entity_list(user_input.get(CONF_MANAGED_ENERGY_ENTITIES))
        )
    ]


def _clean_managed_load_data(user_input: dict[str, Any]) -> dict[str, str]:
    """Normalize persisted managed-load data."""
    data = {CONF_MANAGED_ENERGY_ENTITY: str(user_input[CONF_MANAGED_ENERGY_ENTITY])}
    requested_entity_id = user_input.get(CONF_REQUESTED_ENERGY_ENTITY)
    if requested_entity_id:
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
    """Validate one managed load and its optional demand override."""
    errors: dict[str, str] = {}
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

    if requested_entity_id := user_input.get(CONF_REQUESTED_ENERGY_ENTITY):
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


def _time_selector() -> selector.TimeSelector:
    return selector.TimeSelector(selector.TimeSelectorConfig())


def _nt_window_defaults(options: dict[str, Any]) -> list[dict[str, str]]:
    windows = options.get(CONF_NT_WINDOWS) or []
    return [
        windows[index] if index < len(windows) else DEFAULT_NT_WINDOWS[index]
        for index in range(2)
    ]


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
    for entity_id in _as_entity_list(user_input.get(CONF_MANAGED_ENERGY_ENTITIES)):
        _validate_energy_sensor_entity(
            hass,
            entity_id,
            CONF_MANAGED_ENERGY_ENTITIES,
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
