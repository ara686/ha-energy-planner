"""Source timing and coalescing through Home Assistant's coordinator and clock."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.energy_planner.coordinator import EnergyPlannerCoordinator
from custom_components.energy_planner.models import PlannerResult


async def advance(hass, freezer, seconds):
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


@pytest.fixture
def coordinator(hass, config_entry, monkeypatch):
    config_entry.add_to_hass(hass)
    instance = EnergyPlannerCoordinator(hass, config_entry)
    monkeypatch.setattr(
        instance,
        "_async_build_data",
        AsyncMock(return_value=PlannerResult("ok", dt_util.now())),
    )
    yield instance
    instance.source_refresh.shutdown()


async def test_sources_share_earliest_deadline(hass, freezer, coordinator):
    await coordinator.async_refresh()
    coordinator._async_build_data.reset_mock()
    queue = coordinator.source_refresh
    queue.schedule("battery_soc", 60)
    await advance(hass, freezer, 5)
    queue.schedule("managed_energy", 60)
    queue.schedule("ev_model", 10)
    await advance(hass, freezer, 9)
    coordinator._async_build_data.assert_not_awaited()
    await advance(hass, freezer, 1)
    coordinator._async_build_data.assert_awaited_once()
    assert coordinator.last_refresh["reasons"] == [
        "battery_soc",
        "ev_model",
        "managed_energy",
    ]
    await advance(hass, freezer, 60)
    coordinator._async_build_data.assert_awaited_once()


async def test_continuous_changes_do_not_postpone_source_deadline(
    hass, freezer, coordinator
):
    for _ in range(6):
        coordinator.source_refresh.schedule("battery_soc", 60)
        await advance(hass, freezer, 9)
    coordinator._async_build_data.assert_not_awaited()
    await advance(hass, freezer, 6)
    coordinator._async_build_data.assert_awaited_once()


@pytest.mark.parametrize("reason", [None, "manual", "ev_boundary"])
async def test_other_refresh_consumes_pending_changes(
    hass, freezer, coordinator, reason
):
    await coordinator.async_refresh()
    coordinator._async_build_data.reset_mock()
    coordinator.source_refresh.schedule("battery_soc", 60)
    coordinator.source_refresh.schedule("managed_energy", 60)
    if reason is None:
        await coordinator.async_refresh()  # Same data-update path as periodic polling.
    else:
        await coordinator.async_request_refresh(reason=reason)
    assert set(coordinator.last_refresh["reasons"]) == {
        "battery_soc",
        "managed_energy",
        *([reason] if reason else []),
    }
    await advance(hass, freezer, 61)
    coordinator._async_build_data.assert_awaited_once()


@pytest.mark.parametrize("fails", [False, True])
async def test_changes_during_computation_get_one_followup(
    hass, freezer, coordinator, monkeypatch, fails
):
    started = asyncio.Event()
    finish = asyncio.Event()
    inputs = []
    hass.states.async_set("sensor.input", "1")

    async def build():
        inputs.append(hass.states.get("sensor.input").state)
        if len(inputs) == 1:
            started.set()
            await finish.wait()
            if fails:
                raise ConfigEntryNotReady("Temporary source failure")
        return PlannerResult("ok", dt_util.now())

    monkeypatch.setattr(coordinator, "_async_build_data", build)
    task = hass.async_create_task(coordinator.async_refresh())
    await started.wait()
    hass.states.async_set("sensor.input", "2")
    coordinator.source_refresh.schedule("battery_soc", 60)
    coordinator.source_refresh.schedule("ev_model", 10)
    # Advance the clock without waiting for the intentionally blocked calculation.
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass, dt_util.utcnow())
    await asyncio.sleep(0)
    assert inputs == ["1"]
    finish.set()
    await task
    await advance(hass, freezer, 1)
    assert inputs == ["1", "2"]
    assert coordinator.last_refresh["success"] is True
    assert coordinator.last_refresh["reasons"] == ["battery_soc", "ev_model"]
    await advance(hass, freezer, 60)
    assert inputs == ["1", "2"]


async def test_unload_cancels_pending_and_late_rearming(hass, freezer, coordinator):
    coordinator.source_refresh.schedule("battery_soc", 60)
    coordinator.source_refresh.shutdown()
    coordinator.source_refresh.finished()
    coordinator.source_refresh.schedule("ev_model", 10)
    await advance(hass, freezer, 61)
    coordinator._async_build_data.assert_not_awaited()


async def test_configured_poll_interval_still_runs(hass, freezer, coordinator):
    coordinator.update_interval = timedelta(minutes=30)
    remove_listener = coordinator.async_add_listener(lambda: None)
    await coordinator.async_refresh()
    assert coordinator.last_refresh["reasons"] == ["setup"]
    coordinator._async_build_data.reset_mock()
    await advance(hass, freezer, 29 * 60)
    coordinator._async_build_data.assert_not_awaited()
    await advance(hass, freezer, 61)
    coordinator._async_build_data.assert_awaited_once()
    assert coordinator.last_refresh["reasons"] == ["periodic"]
    remove_listener()


async def test_loaded_entry_unload_removes_pending_source_timer(
    hass, freezer, config_entry
):
    from homeassistant.setup import async_setup_component

    from custom_components.energy_planner.const import DOMAIN

    from .conftest import set_source_states

    set_source_states(hass)
    config_entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    coordinator = config_entry.runtime_data
    coordinator.async_request_refresh = AsyncMock()
    hass.states.async_set("sensor.battery_soc", "57")
    hass.states.async_set("sensor.ev_energy_total", "201")
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await advance(hass, freezer, 61)
    coordinator.async_request_refresh.assert_not_awaited()


async def test_cancelled_callback_cannot_consume_new_source_request(
    hass, freezer, coordinator, monkeypatch
):
    from custom_components.energy_planner import refresh

    callbacks = []
    track = refresh.async_track_point_in_utc_time

    def capture(hass, action, deadline):
        callbacks.append(action)
        return track(hass, action, deadline)

    monkeypatch.setattr(refresh, "async_track_point_in_utc_time", capture)
    coordinator.source_refresh.schedule("battery_soc", 60)
    obsolete = callbacks[-1]
    await coordinator.async_refresh()
    coordinator._async_build_data.reset_mock()
    coordinator.source_refresh.schedule("ev_model", 10)
    # A timer callback may already be queued when another refresh cancels it.
    await obsolete(dt_util.utcnow())
    coordinator._async_build_data.assert_not_awaited()
    await advance(hass, freezer, 10)
    coordinator._async_build_data.assert_awaited_once()
    assert coordinator.last_refresh["reasons"] == ["ev_model"]
