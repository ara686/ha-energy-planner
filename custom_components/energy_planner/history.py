from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

STORAGE_VERSION = 1


@dataclass(frozen=True)
class CumulativeEnergySample:
    timestamp: datetime
    value: float


@dataclass
class HourlyEnergyBucket:
    hour_start: str
    home_kwh: float = 0.0
    managed_kwh: float = 0.0
    managed_sources: dict[str, float] = field(default_factory=dict)

    @property
    def base_kwh(self) -> float:
        return max(self.home_kwh - self.managed_kwh, 0.0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "hour_start": self.hour_start,
            "home_kwh": round(self.home_kwh, 6),
            "managed_kwh": round(self.managed_kwh, 6),
            "managed_sources": {
                source: round(value, 6)
                for source, value in sorted(self.managed_sources.items())
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HourlyEnergyBucket:
        managed_sources = _float_dict(data.get("managed_sources"))
        return cls(
            hour_start=str(data["hour_start"]),
            home_kwh=float(data.get("home_kwh", 0.0)),
            managed_kwh=float(data.get("managed_kwh", sum(managed_sources.values()))),
            managed_sources=managed_sources,
        )


@dataclass
class CumulativeHourlyReading:
    hour_start: str
    value: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "hour_start": self.hour_start,
            "value": round(self.value, 6),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CumulativeHourlyReading:
        return cls(
            hour_start=str(data["hour_start"]),
            value=float(data.get("value", 0.0)),
        )


@dataclass
class EnergyHistory:
    buckets: dict[str, HourlyEnergyBucket] = field(default_factory=dict)
    cumulative_readings: dict[str, CumulativeHourlyReading] = field(
        default_factory=dict
    )
    managed_source_totals: dict[str, float] = field(default_factory=dict)
    dirty: bool = False

    def add_hourly_sample(
        self,
        timestamp: datetime,
        *,
        home_kwh: float,
        managed_kwh: float = 0.0,
        managed_source_id: str | None = None,
    ) -> None:
        home_delta = max(home_kwh, 0.0)
        managed_delta = max(managed_kwh, 0.0)
        if home_delta == 0 and managed_delta == 0:
            return
        key = hour_key(timestamp)
        bucket = self.buckets.setdefault(key, HourlyEnergyBucket(hour_start=key))
        bucket.home_kwh += home_delta
        bucket.managed_kwh += managed_delta
        if managed_delta > 0 and managed_source_id:
            bucket.managed_sources[managed_source_id] = (
                bucket.managed_sources.get(managed_source_id, 0.0) + managed_delta
            )
        self.dirty = True

    def base_consumption_for_hour(self, key: str) -> float:
        bucket = self.buckets.get(key)
        return bucket.base_kwh if bucket else 0.0

    def hourly_points(
        self,
        *,
        now: datetime,
        learning_days: int,
        point_limit: int | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Return compact hourly history points for visualization."""
        cutoff = now - timedelta(days=max(1, learning_days))
        current_key = hour_key(now)
        points = [
            {
                "timestamp": bucket.hour_start,
                "home_kwh": round(bucket.home_kwh, 6),
                "managed_kwh": round(bucket.managed_kwh, 6),
                "managed_sources": {
                    source: round(value, 6)
                    for source, value in sorted(bucket.managed_sources.items())
                },
                "base_kwh": round(bucket.base_kwh, 6),
                "is_current_hour": bucket.hour_start == current_key,
            }
            for key, bucket in sorted(
                self.buckets.items(),
                key=lambda item: _datetime_sort_value(item[0]),
            )
            if _datetime_sort_value(key) >= _datetime_value(cutoff)
        ]
        if point_limit is None or len(points) <= point_limit:
            return points, False
        return points[-point_limit:], True

    @classmethod
    def from_cumulative_energy_samples(
        cls,
        *,
        home_samples: list[CumulativeEnergySample],
        managed_samples_by_source: dict[str, list[CumulativeEnergySample]]
        | None = None,
    ) -> EnergyHistory:
        """Build hourly history from cumulative energy source samples."""
        managed_by_hour: dict[str, float] = {}
        managed_sources_by_hour: dict[str, dict[str, float]] = {}
        for source_id, samples in (managed_samples_by_source or {}).items():
            for key, value in _positive_deltas_by_hour(samples).items():
                managed_by_hour[key] = managed_by_hour.get(key, 0.0) + value
                source_values = managed_sources_by_hour.setdefault(key, {})
                source_values[source_id] = source_values.get(source_id, 0.0) + value

        home_by_hour = _positive_deltas_by_hour(home_samples)
        history = cls()
        for key in home_by_hour.keys() | managed_by_hour.keys():
            history.buckets[key] = HourlyEnergyBucket(
                hour_start=key,
                home_kwh=home_by_hour.get(key, 0.0),
                managed_kwh=managed_by_hour.get(key, 0.0),
                managed_sources=managed_sources_by_hour.get(key, {}),
            )
        return history

    def record_cumulative_energy_source(
        self,
        timestamp: datetime,
        *,
        source_type: str,
        source_id: str,
        value: float,
    ) -> None:
        """Record a cumulative energy source reading."""
        if value < 0:
            return

        key = hour_key(timestamp)
        previous = self.cumulative_readings.get(source_id)
        delta = 0.0
        if previous:
            delta = value - previous.value
            if delta < 0:
                delta = 0.0

        if previous is None or previous.value != value:
            self.cumulative_readings[source_id] = CumulativeHourlyReading(
                hour_start=key,
                value=value,
            )
            self.dirty = True

        if delta <= 0:
            return
        if source_type == "home":
            self.add_hourly_sample(timestamp, home_kwh=delta)
        elif source_type == "managed":
            source_entity_id = _source_entity_id(source_type, source_id)
            self.add_hourly_sample(
                timestamp,
                home_kwh=0.0,
                managed_kwh=delta,
                managed_source_id=source_entity_id,
            )
            self.managed_source_totals[source_entity_id] = (
                self.managed_source_totals.get(source_entity_id, 0.0) + delta
            )
            self.dirty = True

    def managed_source_current_hour_kwh(
        self,
        source_id: str,
        *,
        now: datetime,
    ) -> float:
        return self._managed_source_bucket_kwh(source_id, hour_key(now))

    def managed_source_last_hour_kwh(
        self,
        source_id: str,
        *,
        now: datetime,
    ) -> float:
        return self._managed_source_bucket_kwh(
            source_id,
            hour_key(now - timedelta(hours=1)),
        )

    def managed_source_today_kwh(
        self,
        source_id: str,
        *,
        now: datetime,
    ) -> float:
        today = now.date()
        return sum(
            bucket.managed_sources.get(source_id, 0.0)
            for key, bucket in self.buckets.items()
            if datetime.fromisoformat(key).date() == today
        )

    def managed_source_tracked_total_kwh(self, source_id: str) -> float:
        return self.managed_source_totals.get(source_id, 0.0)

    def managed_source_hourly_points(
        self,
        source_id: str,
        *,
        now: datetime,
        learning_days: int,
        point_limit: int | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Return compact per-source managed history points for visualization."""
        cutoff = now - timedelta(days=max(1, learning_days))
        current_key = hour_key(now)
        points = [
            {
                "timestamp": bucket.hour_start,
                "managed_kwh": round(
                    bucket.managed_sources.get(source_id, 0.0),
                    6,
                ),
                "is_current_hour": bucket.hour_start == current_key,
            }
            for key, bucket in sorted(
                self.buckets.items(),
                key=lambda item: _datetime_sort_value(item[0]),
            )
            if _datetime_sort_value(key) >= _datetime_value(cutoff)
            and bucket.managed_sources.get(source_id, 0.0) > 0
        ]
        if point_limit is None or len(points) <= point_limit:
            return points, False
        return points[-point_limit:], True

    def _managed_source_bucket_kwh(self, source_id: str, key: str) -> float:
        bucket = self.buckets.get(key)
        if bucket is None:
            return 0.0
        return bucket.managed_sources.get(source_id, 0.0)

    def hourly_base_consumption_profile(
        self,
        *,
        now: datetime,
        learning_days: int,
        margin_percent: float,
        include_current_hour: bool = True,
    ) -> dict[int, float]:
        """Return hourly average base consumption by hour of day."""
        cutoff = now - timedelta(days=max(1, learning_days))
        current_key = hour_key(now)
        grouped: dict[int, list[float]] = {}
        for key, bucket in self.buckets.items():
            bucket_time = datetime.fromisoformat(key)
            if _datetime_value(bucket_time) < _datetime_value(cutoff):
                continue
            if not include_current_hour and key == current_key:
                continue
            grouped.setdefault(bucket_time.hour, []).append(bucket.base_kwh)

        multiplier = 1 + margin_percent / 100
        return {
            hour: round((sum(values) / len(values)) * multiplier, 2)
            for hour, values in grouped.items()
            if values
        }

    def cleanup(self, *, now: datetime, retention_days: int) -> None:
        cutoff = now - timedelta(days=max(1, retention_days))
        retained = {
            key: bucket
            for key, bucket in self.buckets.items()
            if _datetime_sort_value(key) >= _datetime_value(cutoff)
        }
        if retained.keys() != self.buckets.keys():
            self.buckets = retained
            self.dirty = True

    def status(self, *, now: datetime, learning_days: int) -> dict[str, Any]:
        cutoff = now - timedelta(days=max(1, learning_days))
        usable_bucket_count = sum(
            1
            for key in self.buckets
            if _datetime_sort_value(key) >= _datetime_value(cutoff)
        )
        return {
            "bucket_count": len(self.buckets),
            "usable_bucket_count": usable_bucket_count,
            "learning_days": learning_days,
            "has_completed_bucket": any(key != hour_key(now) for key in self.buckets),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "buckets": [
                bucket.as_dict()
                for bucket in sorted(
                    self.buckets.values(),
                    key=lambda item: _datetime_sort_value(item.hour_start),
                )
            ],
            "cumulative_readings": {
                source: reading.as_dict()
                for source, reading in sorted(self.cumulative_readings.items())
            },
            "managed_source_totals": {
                source: round(value, 6)
                for source, value in sorted(self.managed_source_totals.items())
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> EnergyHistory:
        if not data:
            return cls()
        buckets = {
            bucket.hour_start: bucket
            for bucket in (
                HourlyEnergyBucket.from_dict(item)
                for item in data.get("buckets", [])
                if isinstance(item, dict) and "hour_start" in item
            )
        }
        raw_readings = data.get("cumulative_readings", {})
        cumulative_readings = (
            {
                str(source): CumulativeHourlyReading.from_dict(item)
                for source, item in raw_readings.items()
                if isinstance(item, dict) and "hour_start" in item
            }
            if isinstance(raw_readings, dict)
            else {}
        )
        return cls(
            buckets=buckets,
            cumulative_readings=cumulative_readings,
            managed_source_totals=_float_dict(data.get("managed_source_totals")),
        )


class EnergyHistoryStore:
    """HA storage backed persistence for Energy Planner history."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        from homeassistant.helpers.storage import Store

        self._store = Store(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}_{entry_id}_history",
        )

    async def async_load(self) -> EnergyHistory:
        return EnergyHistory.from_dict(await self._store.async_load())

    async def async_save(self, history: EnergyHistory) -> None:
        await self._store.async_save(history.as_dict())
        history.dirty = False

    async def async_remove(self) -> None:
        await self._store.async_remove()


def hour_key(timestamp: datetime) -> str:
    return timestamp.replace(minute=0, second=0, microsecond=0).isoformat()


def _datetime_sort_value(value: str) -> float:
    return _datetime_value(datetime.fromisoformat(value))


def _datetime_value(value: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()


def _positive_deltas_by_hour(
    samples: list[CumulativeEnergySample],
) -> dict[str, float]:
    values: dict[str, float] = {}
    previous_value: float | None = None
    for sample in sorted(samples, key=lambda item: item.timestamp):
        if sample.value < 0:
            continue
        if previous_value is None:
            previous_value = sample.value
            continue
        delta = sample.value - previous_value
        previous_value = sample.value
        if delta <= 0:
            continue
        key = hour_key(sample.timestamp)
        values[key] = values.get(key, 0.0) + delta
    return values


def _float_dict(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    parsed: dict[str, float] = {}
    for key, raw_value in value.items():
        try:
            parsed[str(key)] = max(float(raw_value), 0.0)
        except (TypeError, ValueError):
            continue
    return parsed


def _source_entity_id(source_type: str, source_id: str) -> str:
    return source_id.removeprefix(f"{source_type}:")
