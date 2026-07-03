from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

import homeassistant.helpers.config_validation as cv
from homeassistant.exceptions import ServiceValidationError

from .const import DOMAIN

PLATFORMS = ["sensor"]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up Energy Planner services."""

    def _loaded_coordinators() -> list[Any]:
        coordinators = [
            coordinator
            for entry in hass.config_entries.async_entries(DOMAIN)
            if (coordinator := getattr(entry, "runtime_data", None)) is not None
        ]
        if not coordinators:
            raise ServiceValidationError("No loaded Energy Planner config entry found")
        return coordinators

    async def _handle_recalculate(call) -> None:
        for coordinator in _loaded_coordinators():
            await coordinator.async_request_refresh()

    async def _handle_export_debug(call) -> None:
        payload = {
            entry.entry_id: getattr(entry.runtime_data.data, "debug", {})
            for entry in hass.config_entries.async_entries(DOMAIN)
            if getattr(entry, "runtime_data", None) is not None
            and getattr(entry.runtime_data, "data", None) is not None
        }
        if not payload:
            _loaded_coordinators()
        _LOGGER.info("Energy Planner debug export: %s", payload)
        hass.bus.async_fire(f"{DOMAIN}_debug_exported", payload)

    hass.services.async_register(DOMAIN, "recalculate", _handle_recalculate)
    hass.services.async_register(DOMAIN, "export_debug", _handle_export_debug)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Energy Planner from a config entry."""
    from .coordinator import EnergyPlannerCoordinator

    coordinator = EnergyPlannerCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry.runtime_data = None
    return unload_ok
