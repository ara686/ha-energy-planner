"""Fixed joint power limits, legacy sources and their Options Flow conversion."""

from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import selector

from custom_components.energy_planner.coordinator import build_planner_result
from custom_components.energy_planner.joint_options import (
    POWER_LIMIT_ENTITIES,
    normalize_joint_options,
)

from .conftest import options_flow_input, set_source_states


@pytest.mark.parametrize("key", POWER_LIMIT_ENTITIES)
@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), "oops", True])
def test_invalid_static_power_limit(key, value):
    with pytest.raises((TypeError, ValueError)):
        normalize_joint_options({key: value})


@pytest.mark.parametrize("key", POWER_LIMIT_ENTITIES)
@pytest.mark.parametrize("value", [0, 5.75, "11.5", None])
def test_optional_static_power_limit(key, value):
    options = normalize_joint_options({key: value})
    if value is None:
        assert key not in options
    else:
        assert options[key] == float(value)


async def test_static_power_limit_options_schema_and_save(hass, config_entry):
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    fields = {key.schema: value for key, value in result["data_schema"].schema.items()}
    for key, legacy_key in POWER_LIMIT_ENTITIES.items():
        assert legacy_key not in fields
        assert isinstance(fields[key], selector.NumberSelector)
        assert fields[key].config["unit_of_measurement"] == "kW"
        assert fields[key].config["mode"] == selector.NumberSelectorMode.BOX
        assert fields[key].config["min"] == 0
        assert fields[key].config["step"] == 0.01
    limits = dict(zip(POWER_LIMIT_ENTITIES, [17.25, 5.5, 6.0, 0, 5.75], strict=True))
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=options_flow_input(**limits)
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    for key, value in limits.items():
        assert result["data"][key] == value
    reopened = await hass.config_entries.options.async_init(config_entry.entry_id)
    suggested = {
        key.schema: key.description.get("suggested_value")
        for key in reopened["data_schema"].schema
        if key.description
    }
    assert {key: suggested[key] for key in limits} == limits


async def test_clearing_static_limits_removes_saved_values(hass, config_entry):
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        options={**config_entry.options, **dict.fromkeys(POWER_LIMIT_ENTITIES, 5)},
    )
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=options_flow_input()
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert not set(POWER_LIMIT_ENTITIES).intersection(result["data"])


@pytest.mark.parametrize("key", POWER_LIMIT_ENTITIES)
async def test_invalid_static_limit_options_flow(hass, config_entry, key):
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    with pytest.raises(InvalidData) as error:
        await hass.config_entries.options.async_configure(
            result["flow_id"], user_input=options_flow_input(**{key: -1})
        )
    assert error.value.path == [key]


async def test_cleared_limit_stays_empty_after_other_validation_error(
    hass, config_entry
):
    config_entry.add_to_hass(hass)
    key = "joint_export_limit_kw"
    hass.config_entries.async_update_entry(
        config_entry, options={**config_entry.options, key: 5}
    )
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=options_flow_input(joint_voltage=0)
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]
    field = next(field for field in result["data_schema"].schema if field.schema == key)
    assert field.description["suggested_value"] is None


@pytest.mark.parametrize(
    "state,unit,expected",
    [
        ("5750", "W", 5.75),
        ("5.75", "kW", 5.75),
        ("unavailable", "kW", None),
        ("5", "A", None),
        ("-1", "kW", None),
    ],
)
async def test_legacy_limits_are_suggested_in_kw_and_replaced_on_save(
    hass, config_entry, state, unit, expected
):
    config_entry.add_to_hass(hass)
    legacy = dict.fromkeys(POWER_LIMIT_ENTITIES.values(), "sensor.legacy_limit")
    hass.config_entries.async_update_entry(
        config_entry, options={**config_entry.options, **legacy}
    )
    hass.states.async_set("sensor.legacy_limit", state, {"unit_of_measurement": unit})
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    suggested = {
        key.schema: key.description.get("suggested_value")
        for key in result["data_schema"].schema
        if key.description
    }
    for key in POWER_LIMIT_ENTITIES:
        assert suggested[key] == expected
    limits = (
        dict.fromkeys(POWER_LIMIT_ENTITIES, expected) if expected is not None else {}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=options_flow_input(**limits)
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert not set(legacy).intersection(result["data"])
    for key in POWER_LIMIT_ENTITIES:
        assert result["data"].get(key) == expected


def test_fixed_limits_constrain_joint_plan_and_override_legacy(hass, config_entry):
    set_source_states(hass)
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        options={
            **config_entry.options,
            "joint_planning_mode": "advisory",
            **dict.fromkeys(POWER_LIMIT_ENTITIES, 0),
            **dict.fromkeys(POWER_LIMIT_ENTITIES.values(), "sensor.unavailable_limit"),
        },
    )
    result = build_planner_result(
        hass, config_entry, now=datetime(2026, 9, 14, tzinfo=UTC)
    )
    joint = result.debug["joint_plan"]
    assert not any(w.startswith("invalid_limit_source:") for w in joint["warnings"])
    assert not any(
        f"unverified_{key}" in joint["warnings"]
        for key in (
            "grid_import_kw",
            "battery_charge_kw",
            "battery_discharge_kw",
            "export_kw",
            "phase_limit_kw",
        )
    )
    assert joint["points"]
    for point in joint["points"]:
        assert point["grid_import_kwh"] == 0
        assert point["battery_charge_ac_kwh"] == 0
        assert point["battery_discharge_ac_kwh"] == 0
        assert point["export_kwh"] == 0


def test_omitted_static_limits_remain_unverified(hass, config_entry):
    set_source_states(hass)
    result = build_planner_result(
        hass, config_entry, now=datetime(2026, 9, 14, tzinfo=UTC)
    )
    assert "unverified_grid_import_kw" in result.debug["joint_plan"]["warnings"]


def test_nonzero_fixed_limits_bound_power_in_each_interval(hass, config_entry):
    set_source_states(hass)
    now = datetime(2026, 9, 14, tzinfo=UTC)
    hass.states.async_set(
        "sensor.solcast_today",
        "0",
        {
            "detailedForecast": [
                {
                    "period_start": (now + timedelta(hours=i)).isoformat(),
                    "pv_estimate": 3 if 8 <= i % 24 < 16 else 0,
                    "period_minutes": 60,
                }
                for i in range(48)
            ],
            "generated_at_monotonic": hass.loop.time(),
        },
    )
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        options={
            **config_entry.options,
            "joint_grid_import_limit_kw": 0.1,
            "joint_battery_charge_limit_kw": 0.2,
            "joint_battery_discharge_limit_kw": 0.3,
            "joint_export_limit_kw": 0.4,
            "joint_phase_limit_kw": 5.75,
        },
    )
    result = build_planner_result(hass, config_entry, now=now)
    points = result.debug["joint_plan"]["points"]
    assert points
    assert any(point["battery_charge_ac_kwh"] > 0 for point in points)
    assert any(point["battery_discharge_ac_kwh"] > 0 for point in points)
    for point in points:
        hours = (
            datetime.fromisoformat(point["end"])
            - datetime.fromisoformat(point["start"])
        ).total_seconds() / 3600
        for metric, limit in (
            ("grid_import_kwh", 0.1),
            ("battery_charge_ac_kwh", 0.2),
            ("battery_discharge_ac_kwh", 0.3),
            ("export_kwh", 0.4),
        ):
            assert point[metric] <= limit * hours + 1e-6
