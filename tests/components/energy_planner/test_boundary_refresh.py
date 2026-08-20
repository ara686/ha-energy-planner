from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from homeassistant.core import callback
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.energy_planner import (
    EV_MODEL_REFRESH_DEBOUNCE_SECONDS,
    _next_ev_plan_boundary,
    _register_ev_plan_boundary_refresh,
)
from custom_components.energy_planner.const import DOMAIN
from custom_components.energy_planner.models import PlannerResult


class _CoordinatorStub:
    def __init__(self, data: PlannerResult) -> None:
        self.data = data
        self.async_request_refresh = AsyncMock()
        self._listeners: list[Callable[[], None]] = []

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        @callback
        def remove_listener() -> None:
            self._listeners.remove(listener)

        return remove_listener

    @callback
    def set_data(self, data: PlannerResult) -> None:
        self.data = data
        for listener in list(self._listeners):
            listener()


def _result(*timelines: list[dict[str, object]]) -> PlannerResult:
    return PlannerResult(
        state="ok",
        updated=datetime(2026, 8, 20, tzinfo=UTC),
        plan={
            "ev_charging_plans": {
                f"sensor.ev_{index}": {"timeline": timeline}
                for index, timeline in enumerate(timelines)
            }
        },
    )


def test_next_ev_plan_boundary_uses_earliest_valid_future_time() -> None:
    now = datetime(2026, 8, 20, 20, tzinfo=UTC)
    result = _result(
        [
            {
                "start": "2026-08-20T21:00:00+00:00",
                "end": "2026-08-20T22:00:00+00:00",
            },
            {
                "start": "invalid",
                "end": "2026-08-20T19:00:00+00:00",
            },
        ],
        [
            {
                "start": "2026-08-20T20:30:00+00:00",
                "end": "2026-08-20T20:45:00",
            }
        ],
    )

    assert _next_ev_plan_boundary(result, now=now) == datetime(
        2026, 8, 20, 20, 30, tzinfo=UTC
    )


def test_ev_model_refresh_debounce_is_ten_seconds() -> None:
    assert EV_MODEL_REFRESH_DEBOUNCE_SECONDS == 10


async def test_ev_boundary_timer_refreshes_and_reschedules(
    hass,
    monkeypatch,
) -> None:
    now = datetime(2026, 8, 20, 20, tzinfo=UTC)
    monkeypatch.setattr(dt_util, "utcnow", lambda: now)
    first_boundary = now + timedelta(minutes=5)
    replacement_boundary = now + timedelta(minutes=10)
    coordinator = _CoordinatorStub(
        _result([{"start": first_boundary, "end": now + timedelta(minutes=15)}])
    )
    entry = MockConfigEntry(domain=DOMAIN, title="Energy Planner", data={})

    _register_ev_plan_boundary_refresh(hass, entry, coordinator)
    coordinator.set_data(
        _result(
            [
                {
                    "start": replacement_boundary,
                    "end": now + timedelta(minutes=20),
                }
            ]
        )
    )

    async_fire_time_changed(hass, first_boundary)
    await hass.async_block_till_done()
    coordinator.async_request_refresh.assert_not_awaited()

    async_fire_time_changed(hass, replacement_boundary)
    await hass.async_block_till_done()
    coordinator.async_request_refresh.assert_awaited_once_with()


async def test_ev_boundary_timer_follows_start_transition_and_end(
    hass,
    monkeypatch,
) -> None:
    now = datetime(2026, 8, 20, 20, tzinfo=UTC)
    current_time = [now]
    monkeypatch.setattr(dt_util, "utcnow", lambda: current_time[0])
    start = now + timedelta(minutes=5)
    transition = now + timedelta(minutes=10)
    end = now + timedelta(minutes=15)
    result = _result(
        [
            {"start": start, "end": transition, "mode": "home_battery"},
            {"start": transition, "end": end, "mode": "grid_low_tariff"},
        ]
    )
    coordinator = _CoordinatorStub(result)

    async def refresh() -> None:
        coordinator.set_data(result)

    coordinator.async_request_refresh.side_effect = refresh
    entry = MockConfigEntry(domain=DOMAIN, title="Energy Planner", data={})
    _register_ev_plan_boundary_refresh(hass, entry, coordinator)

    for expected_count, boundary in enumerate((start, transition, end), start=1):
        current_time[0] = boundary
        async_fire_time_changed(hass, boundary)
        await hass.async_block_till_done()
        assert coordinator.async_request_refresh.await_count == expected_count

    async_fire_time_changed(hass, end + timedelta(minutes=5))
    await hass.async_block_till_done()
    assert coordinator.async_request_refresh.await_count == 3


async def test_ev_boundary_timer_is_cancelled_on_unload(hass, monkeypatch) -> None:
    now = datetime(2026, 8, 20, 20, tzinfo=UTC)
    monkeypatch.setattr(dt_util, "utcnow", lambda: now)
    boundary = now + timedelta(minutes=5)
    coordinator = _CoordinatorStub(
        _result([{"start": boundary, "end": now + timedelta(minutes=10)}])
    )
    entry = MockConfigEntry(domain=DOMAIN, title="Energy Planner", data={})

    _register_ev_plan_boundary_refresh(hass, entry, coordinator)
    await entry._async_process_on_unload(hass)
    async_fire_time_changed(hass, boundary)
    await hass.async_block_till_done()

    coordinator.async_request_refresh.assert_not_awaited()
    assert coordinator._listeners == []
