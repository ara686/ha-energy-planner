from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict:
    """Return diagnostics for a config entry."""
    coordinator = getattr(entry, "runtime_data", None)
    result = getattr(coordinator, "data", None)
    entity_registry = er.async_get(hass)
    entities = [
        entity.entity_id
        for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id)
        if entity.domain in {"binary_sensor", "sensor"}
    ]

    return {
        "entry": {
            "title": entry.title,
            "domain": DOMAIN,
            "configured_entities": dict(entry.data),
        },
        "options": dict(entry.options),
        "entities": sorted(entities),
        "last_state": getattr(result, "state", None),
        "last_warnings": getattr(result, "warnings", []),
        "last_plan": getattr(result, "plan", {}),
        "history": getattr(result, "forecast", {}).get("history_status", "unknown")
        if result
        else "unknown",
    }
