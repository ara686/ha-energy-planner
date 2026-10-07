"""One source-change queue with bounded latency and no overlapping requests."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from functools import partial

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util


class SourceRefreshQueue:
    """Merge source changes at the earliest deadline and consume them at refresh.

    A periodic/manual refresh also consumes queued changes. Changes arriving
    during a calculation stay pending for one later refresh, even on HA versions
    whose coordinator debouncer does not support retriggering in flight.
    """

    def __init__(
        self, hass: HomeAssistant, request_refresh: Callable[[], Awaitable[None]]
    ) -> None:
        self._hass = hass
        self._request_refresh = request_refresh
        self._cancel_timer: Callable[[], None] | None = None
        self._deadline: datetime | None = None
        self._reasons: set[str] = set()
        self._running = False
        self._closed = False
        self._generation = 0

    @callback
    def schedule(self, reason: str, delay: float) -> None:
        """Keep the earliest deadline; frequent events cannot postpone it."""
        if self._closed:
            return
        self._reasons.add(reason)
        deadline = dt_util.utcnow() + timedelta(seconds=delay)
        if self._deadline is None or deadline < self._deadline:
            self._deadline = deadline
            self._arm()

    @callback
    def note(self, reason: str) -> None:
        """Record an explicit request which already goes through the coordinator."""
        if not self._closed:
            self._reasons.add(reason)

    @callback
    def _cancel(self) -> None:
        self._generation += 1
        if self._cancel_timer is not None:
            self._cancel_timer()
            self._cancel_timer = None

    @callback
    def _arm(self) -> None:
        self._cancel()
        if self._closed or self._running or self._deadline is None:
            return
        self._cancel_timer = async_track_point_in_utc_time(
            self._hass,
            partial(self._fire, generation=self._generation),
            max(self._deadline, dt_util.utcnow()),
        )

    async def _fire(self, _now: datetime, *, generation: int) -> None:
        if generation != self._generation:
            return
        self._cancel_timer = None
        if self._closed or self._running or self._deadline is None:
            return
        self._deadline = None
        await self._request_refresh()

    @callback
    def started(self, default_reason: str) -> list[str]:
        """Consume only changes preceding the input read."""
        self._cancel()
        self._running = True
        reasons = sorted(self._reasons) or [default_reason]
        self._reasons.clear()
        self._deadline = None
        return reasons

    @callback
    def finished(self) -> None:
        """Re-arm retained changes after the current calculation finishes."""
        self._running = False
        self._arm()

    @callback
    def shutdown(self) -> None:
        """Cancel pending work on unload, including a late calculation finish."""
        self._closed = True
        self._cancel()
        self._reasons.clear()
        self._deadline = None
