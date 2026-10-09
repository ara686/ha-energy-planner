"""Persistent planner settings exposed as dashboard switches."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory

try:
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
except ImportError:
    from homeassistant.helpers.entity_platform import (
        AddEntitiesCallback as AddConfigEntryEntitiesCallback,
    )

from .const import (
    CONF_GRID_CHARGING_ENABLED,
    DEFAULT_GRID_CHARGING_ENABLED,
    DOMAIN,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the grid-charging planning switch."""
    async_add_entities([EnergyPlannerGridChargingSwitch(entry)])


class EnergyPlannerGridChargingSwitch(SwitchEntity):
    """Allow grid charging in the plan without controlling the inverter."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = CONF_GRID_CHARGING_ENABLED
    _attr_icon = "mdi:battery-charging-high"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self.entity_id = f"switch.{DOMAIN}_{CONF_GRID_CHARGING_ENABLED}"
        self._attr_unique_id = f"{entry.entry_id}_{CONF_GRID_CHARGING_ENABLED}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
        }

    @property
    def is_on(self) -> bool:
        return self._entry.options.get(
            CONF_GRID_CHARGING_ENABLED, DEFAULT_GRID_CHARGING_ENABLED
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable grid charging in future planner calculations."""
        self._set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable grid charging in future planner calculations."""
        self._set_enabled(False)

    def _set_enabled(self, enabled: bool) -> None:
        if self.is_on == enabled:
            return
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, CONF_GRID_CHARGING_ENABLED: enabled},
        )
        self.async_write_ha_state()
