from datetime import UTC, datetime

import pytest
from homeassistant.data_entry_flow import FlowResultType

from custom_components.energy_planner.coordinator import build_planner_result
from custom_components.energy_planner.joint_options import normalize_joint_options

from .conftest import options_flow_input, set_source_states


def test_joint_shadow_uses_snapshot_without_replacing_public_targets(
    hass, config_entry
):
    set_source_states(hass)
    result = build_planner_result(
        hass, config_entry, now=datetime(2026, 9, 14, tzinfo=UTC)
    )
    assert result.plan["joint_planning_mode"] == "shadow"
    assert result.debug["joint_comparison"]["same_state_snapshot"]
    assert (
        result.debug["joint_comparison"]["values"]["target_soc"]["compatibility"]
        == result.plan["target_soc"]
    )
    assert result.debug["joint_plan"]["points"]
    assert result.plan["soc_forecast"]["source"] == "ha_entities"


def test_joint_advisory_switches_forecasts_together(hass, config_entry):
    set_source_states(hass)
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        options={**config_entry.options, "joint_planning_mode": "advisory"},
    )
    result = build_planner_result(
        hass, config_entry, now=datetime(2026, 9, 14, tzinfo=UTC)
    )
    assert result.plan["target_soc"] == result.plan["joint_summary"]["target_soc"]
    for name in ("soc_forecast", "soc_forecast_planned", "soc_forecast_with_managed"):
        assert result.plan[name]["source"] == "joint_plan"
    assert (
        result.plan["soc_forecast"]["points"][-1]["soc_percent"]
        == result.plan["soc_at_forecast_horizon_with_managed"]
    )


@pytest.mark.parametrize(
    "values",
    [
        {"joint_ev_phases": 2},
        {"joint_voltage": float("nan")},
        {"joint_water_minimum": 50, "joint_water_normal": 45},
        {"joint_water_deadline": "oops"},
        {"joint_minimum_ev_current": 5},
    ],
)
def test_invalid_joint_options(values):
    with pytest.raises(ValueError):
        normalize_joint_options(values)


async def test_joint_options_flow_preserves_mode_and_limits(hass, config_entry):
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            **options_flow_input(),
            "joint_planning_mode": "shadow",
            "joint_grid_import_limit_entity": "sensor.grid_limit",
            "joint_ev_phases": 1,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["joint_grid_import_limit_entity"] == "sensor.grid_limit"
    assert result["data"]["joint_ev_phases"] == 1


def test_invalid_configured_limit_unavailable_then_recovers(hass, config_entry):
    set_source_states(hass)
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        options={
            **config_entry.options,
            "joint_planning_mode": "advisory",
            "joint_export_limit_entity": "sensor.limit",
        },
    )
    hass.states.async_set("sensor.limit", "unavailable", {"unit_of_measurement": "W"})
    result = build_planner_result(
        hass, config_entry, now=datetime(2026, 9, 14, tzinfo=UTC)
    )
    assert result.state == "insufficient_data"
    assert result.plan["joint_summary"]["target_soc"] is None
    hass.states.async_set("sensor.limit", "3000", {"unit_of_measurement": "W"})
    result = build_planner_result(
        hass, config_entry, now=datetime(2026, 9, 14, tzinfo=UTC)
    )
    assert result.state in {"ok", "warning"}
    assert not any(
        w.startswith("invalid_limit_source:")
        for w in result.debug["joint_plan"]["warnings"]
    )


async def test_advisory_repairs_issue_is_removed_on_unload(hass, config_entry):
    from homeassistant.helpers import issue_registry as ir
    from homeassistant.setup import async_setup_component

    from custom_components.energy_planner.const import DOMAIN

    set_source_states(hass)
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        options={**config_entry.options, "joint_planning_mode": "advisory"},
    )
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    issue_id = f"joint_plan_{config_entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
