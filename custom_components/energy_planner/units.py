"""Unit conversion helpers for Home Assistant source entities."""

from __future__ import annotations

from typing import Any

from homeassistant.const import UnitOfEnergy
from homeassistant.util.unit_conversion import EnergyConverter

from .sources import parse_float


def is_supported_energy_unit(unit: Any) -> bool:
    """Return whether Home Assistant can convert the unit as energy."""
    return isinstance(unit, str) and unit in EnergyConverter.VALID_UNITS


def energy_value_to_kwh(value: Any, unit: Any) -> float | None:
    """Parse an energy value and normalize it to kWh."""
    parsed = parse_float(value)
    if parsed is None or not is_supported_energy_unit(unit):
        return None
    return EnergyConverter.convert(
        parsed,
        unit,
        UnitOfEnergy.KILO_WATT_HOUR,
    )
