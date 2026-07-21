"""Configuration helpers for managed energy loads."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_MANAGED_ENERGY_ENTITIES,
    CONF_MANAGED_ENERGY_ENTITY,
    CONF_REQUESTED_ENERGY_ENTITY,
    MANAGED_LOAD_SUBENTRY,
)


@dataclass(frozen=True)
class ManagedLoadConfig:
    """One managed load configured for surplus allocation."""

    source_entity_id: str
    requested_energy_entity_id: str | None = None
    subentry_id: str | None = None


def managed_load_configs(entry: ConfigEntry) -> list[ManagedLoadConfig]:
    """Return configured managed loads, including the legacy v1 format."""
    loads = [
        ManagedLoadConfig(
            source_entity_id=source_entity_id,
            requested_energy_entity_id=_optional_entity_id(
                subentry.data.get(CONF_REQUESTED_ENERGY_ENTITY)
            ),
            subentry_id=subentry.subentry_id,
        )
        for subentry in entry.subentries.values()
        if subentry.subentry_type == MANAGED_LOAD_SUBENTRY
        and (
            source_entity_id := _optional_entity_id(
                subentry.data.get(CONF_MANAGED_ENERGY_ENTITY)
            )
        )
    ]
    if loads:
        return loads

    raw_entity_ids = entry.data.get(CONF_MANAGED_ENERGY_ENTITIES) or []
    if isinstance(raw_entity_ids, str):
        raw_entity_ids = [raw_entity_ids]
    return [
        ManagedLoadConfig(source_entity_id=entity_id)
        for raw_entity_id in raw_entity_ids
        if (entity_id := _optional_entity_id(raw_entity_id))
    ]


def managed_energy_entity_ids(entry: ConfigEntry) -> list[str]:
    """Return managed cumulative energy entity IDs."""
    return [load.source_entity_id for load in managed_load_configs(entry)]


def _optional_entity_id(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value
