from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

import homeassistant.helpers.config_validation as cv
from homeassistant.core import callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_BATTERY_SOC_ENTITY,
    CONF_HOME_ENERGY_ENTITY,
    CONF_MANAGED_ENERGY_ENTITIES,
    DOMAIN,
)

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
    await coordinator.async_load_history()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    _register_battery_soc_refresh(hass, entry, coordinator)
    _register_energy_source_history(hass, entry, coordinator)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry.runtime_data = None
    return unload_ok


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply updated options to the loaded coordinator."""
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is None:
        return
    coordinator.update_interval_from_options()
    await coordinator.async_request_refresh()


def _register_battery_soc_refresh(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: Any,
) -> None:
    """Refresh planner data when the configured battery SoC changes."""
    entity_id = entry.data.get(CONF_BATTERY_SOC_ENTITY)
    if not entity_id:
        return

    @callback
    def _handle_battery_soc_change(event) -> None:
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        if old_state is not None and old_state.state == new_state.state:
            return
        _LOGGER.debug("Battery SoC changed; scheduling Energy Planner refresh")
        hass.async_create_task(coordinator.async_request_refresh())

    entry.async_on_unload(
        async_track_state_change_event(
            hass,
            [entity_id],
            _handle_battery_soc_change,
        )
    )


def _register_energy_source_history(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: Any,
) -> None:
    """Record changed cumulative energy source states into internal history."""
    tracked_sources = _energy_source_entities(entry)
    if not tracked_sources:
        return

    source_types = {
        entity_id: source_type for entity_id, source_type in tracked_sources
    }

    @callback
    def _handle_energy_source_change(event) -> None:
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        if old_state is not None and old_state.state == new_state.state:
            return
        coordinator.record_energy_source_state(
            entity_id=new_state.entity_id,
            source_type=source_types[new_state.entity_id],
            state=new_state,
        )

    entry.async_on_unload(
        async_track_state_change_event(
            hass,
            [entity_id for entity_id, _source_type in tracked_sources],
            _handle_energy_source_change,
        )
    )


def _energy_source_entities(entry: ConfigEntry) -> list[tuple[str, str]]:
    sources: list[tuple[str, str]] = []
    if home_entity_id := entry.data.get(CONF_HOME_ENERGY_ENTITY):
        sources.append((home_entity_id, "home"))

    raw_managed_entity_ids = entry.data.get(CONF_MANAGED_ENERGY_ENTITIES) or []
    if isinstance(raw_managed_entity_ids, str):
        raw_managed_entity_ids = [raw_managed_entity_ids]

    sources.extend(
        (entity_id, "managed")
        for entity_id in raw_managed_entity_ids
        if isinstance(entity_id, str) and entity_id
    )
    return sources
