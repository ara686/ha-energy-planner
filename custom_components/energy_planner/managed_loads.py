"""Configuration helpers for managed energy loads."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_BOTTOM_TEMPERATURE_ENTITY,
    CONF_CHARGING_EFFICIENCY,
    CONF_HEATER_POWER_KW,
    CONF_MANAGED_ENERGY_ENTITIES,
    CONF_MANAGED_ENERGY_ENTITY,
    CONF_MANAGED_LOAD_TYPE,
    CONF_MAXIMUM_CHARGING_POWER_ENTITY,
    CONF_MAXIMUM_TEMPERATURE_C,
    CONF_MINIMUM_TEMPERATURE_C,
    CONF_PRIORITY,
    CONF_REQUESTED_ENERGY_ENTITY,
    CONF_REQUIRED_ENERGY_ENTITY,
    CONF_TANK_VOLUME_LITERS,
    CONF_THERMAL_CONVERSION_FACTOR,
    CONF_TOP_TEMPERATURE_ENTITY,
    DEFAULT_EV_CHARGING_EFFICIENCY,
    DEFAULT_HOT_WATER_MAXIMUM_TEMPERATURE_C,
    DEFAULT_HOT_WATER_THERMAL_CONVERSION_FACTOR,
    DEFAULT_MANAGED_LOAD_PRIORITY,
    DEFAULT_MANAGED_LOAD_TYPE,
    MANAGED_LOAD_SUBENTRY,
    MANAGED_LOAD_TYPE_ELECTRIC_VEHICLE,
    MANAGED_LOAD_TYPE_HOT_WATER,
)


@dataclass(frozen=True)
class ManagedLoadConfig:
    """One managed load configured for surplus allocation."""

    source_entity_id: str
    load_type: str = DEFAULT_MANAGED_LOAD_TYPE
    priority: int = DEFAULT_MANAGED_LOAD_PRIORITY
    requested_energy_entity_id: str | None = None
    required_energy_entity_id: str | None = None
    maximum_charging_power_entity_id: str | None = None
    charging_efficiency: float = DEFAULT_EV_CHARGING_EFFICIENCY
    top_temperature_entity_id: str | None = None
    bottom_temperature_entity_id: str | None = None
    minimum_temperature_c: float | None = None
    maximum_temperature_c: float = DEFAULT_HOT_WATER_MAXIMUM_TEMPERATURE_C
    tank_volume_liters: float | None = None
    heater_power_kw: float | None = None
    thermal_conversion_factor: float = DEFAULT_HOT_WATER_THERMAL_CONVERSION_FACTOR
    subentry_id: str | None = None

    @property
    def is_hot_water(self) -> bool:
        """Return whether this load uses the hot-water thermal model."""
        return self.load_type == MANAGED_LOAD_TYPE_HOT_WATER

    @property
    def is_electric_vehicle(self) -> bool:
        """Return whether this load uses the electric-vehicle model."""
        return self.load_type == MANAGED_LOAD_TYPE_ELECTRIC_VEHICLE


def managed_load_configs(entry: ConfigEntry) -> list[ManagedLoadConfig]:
    """Return configured managed loads, including the legacy v1 format."""
    loads = [
        ManagedLoadConfig(
            source_entity_id=source_entity_id,
            load_type=str(
                subentry.data.get(CONF_MANAGED_LOAD_TYPE, DEFAULT_MANAGED_LOAD_TYPE)
            ),
            priority=_positive_int(
                subentry.data.get(CONF_PRIORITY), DEFAULT_MANAGED_LOAD_PRIORITY
            ),
            requested_energy_entity_id=_optional_entity_id(
                subentry.data.get(CONF_REQUESTED_ENERGY_ENTITY)
            ),
            required_energy_entity_id=_optional_entity_id(
                subentry.data.get(CONF_REQUIRED_ENERGY_ENTITY)
            ),
            maximum_charging_power_entity_id=_optional_entity_id(
                subentry.data.get(CONF_MAXIMUM_CHARGING_POWER_ENTITY)
            ),
            charging_efficiency=_float_or_default(
                subentry.data.get(CONF_CHARGING_EFFICIENCY),
                DEFAULT_EV_CHARGING_EFFICIENCY,
            ),
            top_temperature_entity_id=_optional_entity_id(
                subentry.data.get(CONF_TOP_TEMPERATURE_ENTITY)
            ),
            bottom_temperature_entity_id=_optional_entity_id(
                subentry.data.get(CONF_BOTTOM_TEMPERATURE_ENTITY)
            ),
            minimum_temperature_c=_optional_float(
                subentry.data.get(CONF_MINIMUM_TEMPERATURE_C)
            ),
            maximum_temperature_c=_float_or_default(
                subentry.data.get(CONF_MAXIMUM_TEMPERATURE_C),
                DEFAULT_HOT_WATER_MAXIMUM_TEMPERATURE_C,
            ),
            tank_volume_liters=_optional_float(
                subentry.data.get(CONF_TANK_VOLUME_LITERS)
            ),
            heater_power_kw=_optional_float(subentry.data.get(CONF_HEATER_POWER_KW)),
            thermal_conversion_factor=_float_or_default(
                subentry.data.get(CONF_THERMAL_CONVERSION_FACTOR),
                DEFAULT_HOT_WATER_THERMAL_CONVERSION_FACTOR,
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


def _optional_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _float_or_default(value: object, default: float) -> float:
    parsed = _optional_float(value)
    return parsed if parsed is not None else default


def _positive_int(value: object, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 1 else default
