from __future__ import annotations

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
    CONF_HOME_ENERGY_HOURLY_ENTITY,
    CONF_INTERVAL_MINUTES,
    CONF_MANAGED_ENERGY_HOURLY_ENTITY,
    CONF_MIN_BASELINE_KWH_PER_HOUR,
    CONF_NT_WINDOWS,
    CONF_PRICE_ENTITY,
    CONF_SOC_EPS_KWH,
    CONF_SOC_RESERVE_PERCENT,
    CONF_SOLCAST_TODAY_ENTITY,
    CONF_SOLCAST_TOMORROW_ENTITY,
    CONF_SUN_START_REQUIRED_MINUTES,
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
                    CONF_INTERVAL_MINUTES,
                    default=options[CONF_INTERVAL_MINUTES],
                ): int,
                vol.Required(
                    CONF_MIN_BASELINE_KWH_PER_HOUR,
                    default=options[CONF_MIN_BASELINE_KWH_PER_HOUR],
                ): float,
                vol.Required(
                    CONF_GRID_CHARGE_MAX_KW,
                    default=options[CONF_GRID_CHARGE_MAX_KW],
                ): float,
                vol.Required(
                    CONF_GRID_CHARGE_EFFICIENCY,
                    default=options[CONF_GRID_CHARGE_EFFICIENCY],
                ): float,
                vol.Required(
                    CONF_SOC_RESERVE_PERCENT,
                    default=options[CONF_SOC_RESERVE_PERCENT],
                ): float,
                vol.Required(
                    CONF_SOC_EPS_KWH,
                    default=options[CONF_SOC_EPS_KWH],
                ): float,
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
                ): int,
                vol.Required(
                    CONF_FORECAST_HORIZON_HOURS,
                    default=options[CONF_FORECAST_HORIZON_HOURS],
                ): int,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )
