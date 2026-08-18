from __future__ import annotations

import logging
import math
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

import homeassistant.helpers.config_validation as cv
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT
from homeassistant.core import callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_BATTERY_SOC_ENTITY,
    CONF_HOME_ENERGY_ENTITY,
    CONF_MANAGED_ENERGY_ENTITIES,
    CONF_MANAGED_ENERGY_ENTITY,
    CONF_MANAGED_LOAD_TYPE,
    CONF_MAXIMUM_CHARGING_POWER_ENTITY,
    CONF_MAXIMUM_CHARGING_POWER_KW,
    CONF_PRIORITY,
    DEFAULT_MANAGED_LOAD_PRIORITY,
    DEFAULT_MANAGED_LOAD_TYPE,
    DOMAIN,
    MANAGED_LOAD_SUBENTRY,
    MANAGED_LOAD_TYPE_ELECTRIC_VEHICLE,
)
from .managed_loads import managed_energy_entity_ids, managed_load_configs
from .units import power_value_to_kw

PLATFORMS = ["binary_sensor", "sensor"]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
_LOGGER = logging.getLogger(__name__)
SOC_REFRESH_DEBOUNCE_SECONDS = 60
MANAGED_SOURCE_REFRESH_DEBOUNCE_SECONDS = 60


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
    _register_managed_model_refresh(hass, entry, coordinator)
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry.runtime_data = None
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove stored data for a config entry."""
    from .history import EnergyHistoryStore

    await EnergyHistoryStore(hass, entry.entry_id).async_remove()


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate legacy managed loads to typed config subentries."""
    if entry.version > 4:
        return False
    if entry.version == 4:
        return True

    data = dict(entry.data)
    if entry.version == 1:
        raw_entity_ids = data.pop(CONF_MANAGED_ENERGY_ENTITIES, []) or []
        if isinstance(raw_entity_ids, str):
            raw_entity_ids = [raw_entity_ids]
        existing_source_ids = {
            subentry.data.get(CONF_MANAGED_ENERGY_ENTITY)
            for subentry in entry.subentries.values()
            if subentry.subentry_type == MANAGED_LOAD_SUBENTRY
        }
        for entity_id in dict.fromkeys(raw_entity_ids):
            if (
                not isinstance(entity_id, str)
                or not entity_id
                or entity_id in existing_source_ids
            ):
                continue
            state = hass.states.get(entity_id)
            hass.config_entries.async_add_subentry(
                entry,
                ConfigSubentry(
                    data=MappingProxyType(
                        {
                            CONF_MANAGED_ENERGY_ENTITY: entity_id,
                            CONF_MANAGED_LOAD_TYPE: DEFAULT_MANAGED_LOAD_TYPE,
                            CONF_PRIORITY: DEFAULT_MANAGED_LOAD_PRIORITY,
                        }
                    ),
                    subentry_type=MANAGED_LOAD_SUBENTRY,
                    title=state.name if state is not None else entity_id,
                    unique_id=entity_id,
                ),
            )

    for subentry in entry.subentries.values():
        if subentry.subentry_type != MANAGED_LOAD_SUBENTRY:
            continue
        subentry_data = dict(subentry.data)
        subentry_data.setdefault(CONF_MANAGED_LOAD_TYPE, DEFAULT_MANAGED_LOAD_TYPE)
        subentry_data.setdefault(CONF_PRIORITY, DEFAULT_MANAGED_LOAD_PRIORITY)
        if (
            subentry_data[CONF_MANAGED_LOAD_TYPE] == MANAGED_LOAD_TYPE_ELECTRIC_VEHICLE
            and CONF_MAXIMUM_CHARGING_POWER_KW not in subentry_data
        ):
            legacy_entity_id = subentry_data.get(CONF_MAXIMUM_CHARGING_POWER_ENTITY)
            legacy_state = (
                hass.states.get(legacy_entity_id)
                if isinstance(legacy_entity_id, str)
                else None
            )
            maximum_power_kw = power_value_to_kw(
                legacy_state.state if legacy_state else None,
                legacy_state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
                if legacy_state
                else None,
            )
            if (
                maximum_power_kw is not None
                and math.isfinite(maximum_power_kw)
                and maximum_power_kw > 0
            ):
                subentry_data[CONF_MAXIMUM_CHARGING_POWER_KW] = maximum_power_kw
            else:
                _LOGGER.warning(
                    "Could not migrate maximum charging power for managed load %s; "
                    "reconfigure the load to restore its EV recommendation",
                    subentry.data.get(CONF_MANAGED_ENERGY_ENTITY),
                )
        subentry_data.pop(CONF_MAXIMUM_CHARGING_POWER_ENTITY, None)
        hass.config_entries.async_update_subentry(
            entry,
            subentry,
            data=subentry_data,
        )
    hass.config_entries.async_update_entry(entry, data=data, version=4)
    return True


async def _async_entry_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration after options or managed loads change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _register_battery_soc_refresh(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: Any,
) -> None:
    """Refresh planner data when the configured battery SoC changes."""
    entity_id = entry.data.get(CONF_BATTERY_SOC_ENTITY)
    if not entity_id:
        return

    async def _request_refresh() -> None:
        await coordinator.async_request_refresh()

    debouncer = Debouncer(
        hass,
        _LOGGER,
        cooldown=SOC_REFRESH_DEBOUNCE_SECONDS,
        immediate=False,
        function=_request_refresh,
    )
    entry.async_on_unload(debouncer.async_cancel)

    @callback
    def _handle_battery_soc_change(event) -> None:
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        if old_state is not None and old_state.state == new_state.state:
            return
        _LOGGER.debug("Battery SoC changed; scheduling Energy Planner refresh")
        hass.async_create_task(debouncer.async_call())

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

    async def _request_refresh() -> None:
        await coordinator.async_request_refresh()

    managed_refresh_debouncer = Debouncer(
        hass,
        _LOGGER,
        cooldown=MANAGED_SOURCE_REFRESH_DEBOUNCE_SECONDS,
        immediate=False,
        function=_request_refresh,
    )
    entry.async_on_unload(managed_refresh_debouncer.async_cancel)

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
            previous_state=old_state,
        )
        if source_types[new_state.entity_id] == "managed":
            hass.async_create_task(managed_refresh_debouncer.async_call())

    entry.async_on_unload(
        async_track_state_change_event(
            hass,
            [entity_id for entity_id, _source_type in tracked_sources],
            _handle_energy_source_change,
        )
    )


def _register_managed_model_refresh(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: Any,
) -> None:
    """Refresh planner data when a managed model input changes."""
    tracked_entities = {
        entity_id
        for load in managed_load_configs(entry)
        if load.load_type == MANAGED_LOAD_TYPE_ELECTRIC_VEHICLE
        for entity_id in (load.required_energy_entity_id,)
        if entity_id
    }
    if not tracked_entities:
        return

    async def _request_refresh() -> None:
        await coordinator.async_request_refresh()

    debouncer = Debouncer(
        hass,
        _LOGGER,
        cooldown=MANAGED_SOURCE_REFRESH_DEBOUNCE_SECONDS,
        immediate=False,
        function=_request_refresh,
    )
    entry.async_on_unload(debouncer.async_cancel)

    @callback
    def _handle_managed_model_change(event) -> None:
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        if (
            old_state is not None
            and old_state.state == new_state.state
            and old_state.attributes == new_state.attributes
        ):
            return
        _LOGGER.debug(
            "Managed model input %s changed; scheduling Energy Planner refresh",
            new_state.entity_id,
        )
        hass.async_create_task(debouncer.async_call())

    entry.async_on_unload(
        async_track_state_change_event(
            hass,
            sorted(tracked_entities),
            _handle_managed_model_change,
        )
    )


def _energy_source_entities(entry: ConfigEntry) -> list[tuple[str, str]]:
    sources: list[tuple[str, str]] = []
    if home_entity_id := entry.data.get(CONF_HOME_ENERGY_ENTITY):
        sources.append((home_entity_id, "home"))

    sources.extend(
        (entity_id, "managed") for entity_id in managed_energy_entity_ids(entry)
    )
    return sources
