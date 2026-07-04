from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfEnergy
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.energy_planner.const import (
    CONF_BATTERY_CAPACITY_ENTITY,
    CONF_BATTERY_MIN_SOC_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_CHARGE_WINDOW,
    CONF_FORECAST_HORIZON_HOURS,
    CONF_GRID_CHARGE_EFFICIENCY,
    CONF_GRID_CHARGE_MAX_KW,
    CONF_HISTORY_CORRECTION_PERCENT,
    CONF_HISTORY_LEARNING_DAYS,
    CONF_HOME_ENERGY_ENTITY,
    CONF_INTERVAL_MINUTES,
    CONF_MANAGED_ENERGY_ENTITIES,
    CONF_MIN_BASELINE_KWH_PER_HOUR,
    CONF_NT_WINDOWS,
    CONF_SOC_EPS_KWH,
    CONF_SOC_RESERVE_PERCENT,
    CONF_SOLCAST_ADDITIONAL_ENTITIES,
    CONF_SOLCAST_TODAY_ENTITY,
    CONF_SOLCAST_TOMORROW_ENTITY,
    CONF_SUN_START_REQUIRED_MINUTES,
    CONF_UPDATE_INTERVAL_MINUTES,
    DOMAIN,
)
from custom_components.energy_planner.options import normalize_options


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations for Home Assistant integration tests."""


def config_data(**overrides: Any) -> dict[str, Any]:
    """Return valid config flow data."""
    data = {
        CONF_BATTERY_SOC_ENTITY: "sensor.battery_soc",
        CONF_BATTERY_CAPACITY_ENTITY: "sensor.battery_capacity",
        CONF_BATTERY_MIN_SOC_ENTITY: "sensor.battery_min_soc",
        CONF_HOME_ENERGY_ENTITY: "sensor.home_energy_total",
        CONF_MANAGED_ENERGY_ENTITIES: [
            "sensor.ev_energy_total",
            "sensor.water_heater_energy_total",
        ],
        CONF_SOLCAST_TODAY_ENTITY: "sensor.solcast_today",
        CONF_SOLCAST_TOMORROW_ENTITY: "sensor.solcast_tomorrow",
        CONF_SOLCAST_ADDITIONAL_ENTITIES: ["sensor.solcast_day_3"],
    }
    data.update(overrides)
    return data


def options_data(**overrides: Any) -> dict[str, Any]:
    """Return normalized options for config entry storage."""
    return normalize_options(options_flow_input(**overrides))


def options_flow_input(**overrides: Any) -> dict[str, Any]:
    """Return options matching the options flow UI schema."""
    data: dict[str, Any] = {
        CONF_UPDATE_INTERVAL_MINUTES: 60,
        CONF_HISTORY_LEARNING_DAYS: 3,
        CONF_INTERVAL_MINUTES: 60,
        CONF_HISTORY_CORRECTION_PERCENT: 5.0,
        CONF_MIN_BASELINE_KWH_PER_HOUR: 0.2,
        CONF_GRID_CHARGE_MAX_KW: 5.5,
        CONF_GRID_CHARGE_EFFICIENCY: 0.92,
        CONF_SOC_RESERVE_PERCENT: 1.0,
        CONF_SOC_EPS_KWH: 0.02,
        CONF_NT_WINDOWS: "17:00-19:00,22:00-04:00",
        CONF_CHARGE_WINDOW: "22:00-04:00",
        CONF_SUN_START_REQUIRED_MINUTES: 30,
        CONF_FORECAST_HORIZON_HOURS: 36,
    }
    data.update(overrides)
    return data


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return a loaded-entry candidate for integration setup tests."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Energy Planner",
        data=config_data(),
        options=options_data(),
        unique_id=DOMAIN,
    )


def set_source_states(hass, *, invalid_required_state: bool = False) -> None:
    """Populate Home Assistant source entities for the planner."""
    hass.states.async_set(
        "sensor.battery_soc",
        "unknown" if invalid_required_state else "55",
        {"unit_of_measurement": PERCENTAGE},
    )
    hass.states.async_set(
        "sensor.battery_capacity",
        "20",
        {"unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR},
    )
    hass.states.async_set(
        "sensor.battery_min_soc",
        "20",
        {"unit_of_measurement": PERCENTAGE},
    )
    hass.states.async_set(
        "sensor.home_energy_total",
        "1000",
        {
            "device_class": SensorDeviceClass.ENERGY,
            "state_class": SensorStateClass.TOTAL,
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )
    hass.states.async_set(
        "sensor.ev_energy_total",
        "200",
        {
            "device_class": SensorDeviceClass.ENERGY,
            "state_class": SensorStateClass.TOTAL_INCREASING,
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )
    hass.states.async_set(
        "sensor.water_heater_energy_total",
        "50",
        {
            "device_class": SensorDeviceClass.ENERGY,
            "state_class": SensorStateClass.TOTAL_INCREASING,
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        },
    )
    hass.states.async_set(
        "sensor.solcast_today",
        "0",
        _forecast_attributes(hass, offset_hours=1),
    )
    hass.states.async_set(
        "sensor.solcast_tomorrow",
        "0",
        _forecast_attributes(hass, offset_hours=24),
    )
    hass.states.async_set(
        "sensor.solcast_day_3",
        "0",
        _forecast_attributes(hass, offset_hours=48),
    )


def _forecast_attributes(hass, *, offset_hours: int) -> dict[str, Any]:
    base = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    return {
        "detailedForecast": [
            {
                "period_start": (
                    base + timedelta(hours=offset_hours + index)
                ).isoformat(),
                "pv_estimate": 0.8,
                "period_minutes": 60,
            }
            for index in range(4)
        ],
        "generated_at_monotonic": hass.loop.time(),
    }
