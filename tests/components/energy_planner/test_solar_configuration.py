"""HA configuration adapters and public solar planning contracts."""

from datetime import UTC, datetime, timedelta

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.energy_planner.const import (
    CONF_BOTTOM_TEMPERATURE_ENTITY,
    CONF_CHARGING_EFFICIENCY,
    CONF_FORECAST_HORIZON_HOURS,
    CONF_GRID_CHARGING_ENABLED,
    CONF_HEATER_POWER_KW,
    CONF_INTERVAL_MINUTES,
    CONF_MANAGED_ENERGY_ENTITY,
    CONF_MANAGED_LOAD_TYPE,
    CONF_MAXIMUM_CHARGING_POWER_KW,
    CONF_MAXIMUM_TEMPERATURE_C,
    CONF_MIN_BASELINE_KWH_PER_HOUR,
    CONF_MINIMUM_TEMPERATURE_C,
    CONF_PRIORITY,
    CONF_REQUIRED_ENERGY_ENTITY,
    CONF_SOLAR_MINIMUM_SOC_PERCENT,
    CONF_SOLCAST_ADDITIONAL_ENTITIES,
    CONF_SOLCAST_TOMORROW_ENTITY,
    CONF_TANK_VOLUME_LITERS,
    CONF_THERMAL_CONVERSION_FACTOR,
    CONF_TOP_TEMPERATURE_ENTITY,
    DOMAIN,
    MANAGED_LOAD_SUBENTRY,
    MANAGED_LOAD_TYPE_ELECTRIC_VEHICLE,
    MANAGED_LOAD_TYPE_HOT_WATER,
)
from custom_components.energy_planner.coordinator import (
    _electric_vehicle_allocation_input,
    _hot_water_allocation_input,
    _minimum_solar_ev_power_kw,
    build_planner_result,
)
from custom_components.energy_planner.managed_allocation import (
    UnavailableAllocationInput,
)
from custom_components.energy_planner.managed_loads import managed_load_configs

from .conftest import config_data, options_data, set_source_states


def _entry(mode="shadow", **options):
    return MockConfigEntry(
        domain=DOMAIN,
        version=5,
        unique_id=DOMAIN,
        data=config_data(
            **{CONF_SOLCAST_TOMORROW_ENTITY: None, CONF_SOLCAST_ADDITIONAL_ENTITIES: []}
        ),
        options={
            **options_data(
                **{
                    CONF_GRID_CHARGING_ENABLED: False,
                    CONF_FORECAST_HORIZON_HOURS: 48,
                    CONF_INTERVAL_MINUTES: 60,
                    CONF_MIN_BASELINE_KWH_PER_HOUR: 0.7,
                }
            ),
            "joint_planning_mode": mode,
            **options,
        },
        subentries_data=(
            {
                "data": {
                    CONF_MANAGED_ENERGY_ENTITY: "sensor.water_heater_energy_total",
                    CONF_MANAGED_LOAD_TYPE: MANAGED_LOAD_TYPE_HOT_WATER,
                    CONF_PRIORITY: 100,
                    CONF_TOP_TEMPERATURE_ENTITY: "sensor.water_top",
                    CONF_BOTTOM_TEMPERATURE_ENTITY: "sensor.water_bottom",
                    CONF_MINIMUM_TEMPERATURE_C: 45,
                    CONF_MAXIMUM_TEMPERATURE_C: 45.1,
                    CONF_TANK_VOLUME_LITERS: 200,
                    CONF_HEATER_POWER_KW: 2.3,
                    CONF_THERMAL_CONVERSION_FACTOR: 1,
                },
                "subentry_type": MANAGED_LOAD_SUBENTRY,
                "title": "Water",
                "unique_id": "sensor.water_heater_energy_total",
            },
            {
                "data": {
                    CONF_MANAGED_ENERGY_ENTITY: "sensor.ev_energy_total",
                    CONF_MANAGED_LOAD_TYPE: MANAGED_LOAD_TYPE_ELECTRIC_VEHICLE,
                    CONF_PRIORITY: 100,
                    CONF_REQUIRED_ENERGY_ENTITY: "input_number.ev_energy_request",
                    CONF_MAXIMUM_CHARGING_POWER_KW: 11,
                    CONF_CHARGING_EFFICIENCY: 1,
                },
                "subentry_type": MANAGED_LOAD_SUBENTRY,
                "title": "EV",
                "unique_id": "sensor.ev_energy_total",
            },
        ),
    )


def _states(hass, now):
    set_source_states(hass)
    hass.states.async_set("sensor.battery_soc", "40", {"unit_of_measurement": "%"})
    for entity in ("sensor.water_top", "sensor.water_bottom"):
        hass.states.async_set(
            entity, "40", {"unit_of_measurement": "°C", "device_class": "temperature"}
        )
    hass.states.async_set(
        "input_number.ev_energy_request", "5", {"unit_of_measurement": "kWh"}
    )
    hass.states.async_set(
        "sensor.solcast_today",
        "0",
        {
            "detailedForecast": [
                {
                    "period_start": (now + timedelta(hours=i)).isoformat(),
                    "pv_estimate": 6 if 10 <= (now.hour + i) % 24 < 18 else 0,
                    "period_minutes": 60,
                }
                for i in range(48)
            ],
            "generated_at_monotonic": hass.loop.time(),
        },
    )


@pytest.mark.parametrize("mode", ["shadow", "advisory"])
def test_old_configuration_defaults_to_50_and_public_graphs_follow_solar_gate(
    hass, mode
):
    now = datetime(2026, 9, 14, 10, tzinfo=UTC)
    _states(hass, now)
    entry = _entry(mode)
    assert all(
        load.solar_minimum_soc_percent == 50 for load in managed_load_configs(entry)
    )
    result = build_planner_result(hass, entry, now=now)
    assert result.plan["joint_planning_mode"] == mode
    managed = result.plan["soc_forecast_with_managed"]["points"]
    active = [point for point in managed if point.get("managed_consumption_kwh", 0) > 0]
    assert active
    assert all(point["battery_start_kwh"] >= 10 - 1e-9 for point in active)
    assert all(
        point["solar_kwh"] + 1e-6 >= point["consumption_kwh"] for point in active
    )
    assert all(point["grid_charge_kwh"] == 0 for point in managed)
    assert not result.plan.get("charge_now", False)
    assert result.plan["managed_recommended_today_kwh"] > 0
    # Both planner variants also satisfy the gates in the joint diagnostic ledger.
    for point in result.debug["joint_plan"]["points"]:
        if point["managed_by_source"]:
            assert point["battery_start_kwh"] >= 10 - 1e-9
    if mode == "advisory":
        vehicle = result.plan["ev_charging_plans"]["sensor.ev_energy_total"]
        assert vehicle["planned_kwh"] > 0
        assert all(action["mode"] == "solar" for action in vehicle["timeline"])
        assert sum(
            action["energy_kwh"] for action in vehicle["timeline"]
        ) == pytest.approx(vehicle["planned_kwh"])


@pytest.mark.parametrize(
    "value", [-1, 101, float("nan"), float("inf"), None, "invalid"]
)
def test_invalid_stored_solar_threshold_withholds_only_that_load(hass, value):
    now = datetime(2026, 9, 14, 10, tzinfo=UTC)
    _states(hass, now)
    entry = _entry()
    entry.add_to_hass(hass)
    for subentry in list(entry.subentries.values()):
        hass.config_entries.async_update_subentry(
            entry,
            subentry,
            data={**subentry.data, CONF_SOLAR_MINIMUM_SOC_PERCENT: value},
        )
    water, ev = managed_load_configs(entry)
    assert isinstance(
        _hot_water_allocation_input(hass, water, []), UnavailableAllocationInput
    )
    assert isinstance(
        _electric_vehicle_allocation_input(hass, ev, []), UnavailableAllocationInput
    )


@pytest.mark.parametrize(
    "phases,current,voltage,expected", [(1, 6, 230, 1.38), (3, 8, 240, 5.76)]
)
def test_all_solar_strategies_derive_ev_minimum_from_configured_electrics(
    phases, current, voltage, expected
):
    entry = _entry(
        joint_solar_ev_phases=phases,
        joint_minimum_ev_current=current,
        joint_voltage=voltage,
    )
    assert _minimum_solar_ev_power_kw(entry) == pytest.approx(expected)
