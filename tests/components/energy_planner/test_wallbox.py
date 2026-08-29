"""Tests for pure wallbox mode recommendations."""

from custom_components.energy_planner.wallbox import (
    WallboxModeOptions,
    recommended_wallbox_mode,
    wallbox_charging_source,
)


def test_wallbox_mode_mapping_uses_safe_off_for_non_charging_modes() -> None:
    options = WallboxModeOptions(
        solar="EKO - Solar",
        home_battery="Battery Free kWh",
        grid="GRID",
        off="OFF",
    )

    assert recommended_wallbox_mode("solar", options) == "EKO - Solar"
    assert recommended_wallbox_mode("home_battery", options) == "Battery Free kWh"
    assert recommended_wallbox_mode("grid_low_tariff", options) == "GRID"
    assert recommended_wallbox_mode("grid_high_tariff", options) == "GRID"
    for mode in (
        "off",
        "connect_vehicle",
        "wait_for_solar",
        "complete",
        "shortfall",
        "unavailable",
        None,
    ):
        assert recommended_wallbox_mode(mode, options) == "OFF"


def test_wallbox_mode_options_are_distinct_and_stable() -> None:
    options = WallboxModeOptions("solar", "battery", "grid", "grid")

    assert options.values == ("solar", "battery", "grid")


def test_wallbox_option_maps_back_to_observed_source() -> None:
    options = WallboxModeOptions("Solar", "Battery", "Grid", "Off")

    assert wallbox_charging_source("Solar", options) == "solar"
    assert wallbox_charging_source("Battery", options) == "home_battery"
    assert wallbox_charging_source("Grid", options) == "grid"
    assert wallbox_charging_source("Off", options) is None
    assert wallbox_charging_source("Unknown", options) is None
