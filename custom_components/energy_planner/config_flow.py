from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
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
    CONF_HOME_ENERGY_HOURLY_ENTITY,
    CONF_INTERVAL_MINUTES,
    CONF_MANAGED_ENERGY_HOURLY_ENTITY,
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
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=DEFAULT_NAME, data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_BATTERY_SOC_ENTITY): selector.EntitySelector(),
                vol.Required(CONF_BATTERY_CAPACITY_ENTITY): selector.EntitySelector(),
                vol.Required(CONF_BATTERY_MIN_SOC_ENTITY): selector.EntitySelector(),
                vol.Required(CONF_HOME_ENERGY_HOURLY_ENTITY): selector.EntitySelector(),
                vol.Optional(
                    CONF_MANAGED_ENERGY_HOURLY_ENTITY
                ): selector.EntitySelector(),
                vol.Optional(CONF_SOLCAST_TODAY_ENTITY): selector.EntitySelector(),
                vol.Optional(CONF_SOLCAST_TOMORROW_ENTITY): selector.EntitySelector(),
                vol.Optional(CONF_SOLCAST_ADDITIONAL_ENTITIES): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", multiple=True)
                ),
                vol.Optional(CONF_PRICE_ENTITY): selector.EntitySelector(),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
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
