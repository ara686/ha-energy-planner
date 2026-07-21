from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from math import ceil
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
    observed_sources: set[str] = field(default_factory=set)

    @property
    def base_kwh(self) -> float:
        return max(self.home_kwh - self.managed_kwh, 0.0)

    @property
    def base_usable(self) -> bool:
        return self.home_kwh > 0 and self.home_kwh + 1e-9 >= self.managed_kwh

    def as_dict(self) -> dict[str, Any]:
        return {
            "hour_start": self.hour_start,
            "home_kwh": round(self.home_kwh, 6),
            "managed_kwh": round(self.managed_kwh, 6),
            "managed_sources": {
                source: round(value, 6)
                for source, value in sorted(self.managed_sources.items())
            },
            "observed_sources": sorted(self.observed_sources),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HourlyEnergyBucket:
        managed_sources = _float_dict(data.get("managed_sources"))
        return cls(
            hour_start=str(data["hour_start"]),
            home_kwh=float(data.get("home_kwh", 0.0)),
            managed_kwh=float(data.get("managed_kwh", sum(managed_sources.values()))),
            managed_sources=managed_sources,
            observed_sources={
                str(source) for source in data.get("observed_sources", [])
            },
        )


@dataclass(frozen=True)
class DailyManagedEnergy:
    date: date
    energy_kwh: float
    observed_hours: int
    expected_hours: int

    @property
    def coverage_ratio(self) -> float:
        if self.expected_hours <= 0:
            return 0.0
        return min(self.observed_hours / self.expected_hours, 1.0)


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
        observed_source_ids: set[str] | None = None,
    ) -> None:
        home_delta = max(home_kwh, 0.0)
        managed_delta = max(managed_kwh, 0.0)
        observed_source_ids = observed_source_ids or set()
        if home_delta == 0 and managed_delta == 0 and not observed_source_ids:
            return
        key = hour_key(timestamp)
        bucket = self.buckets.setdefault(key, HourlyEnergyBucket(hour_start=key))
        new_observations = observed_source_ids - bucket.observed_sources
        if home_delta == 0 and managed_delta == 0 and not new_observations:
            return
        bucket.home_kwh += home_delta
        bucket.managed_kwh += managed_delta
        if managed_delta > 0 and managed_source_id:
            bucket.managed_sources[managed_source_id] = (
                bucket.managed_sources.get(managed_source_id, 0.0) + managed_delta
            )
        bucket.observed_sources.update(new_observations)
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
                "base_usable": bucket.base_usable,
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
        home_source_id: str = "home",
    ) -> EnergyHistory:
        """Build hourly history from cumulative energy source samples."""
        managed_by_hour: dict[str, float] = {}
        managed_sources_by_hour: dict[str, dict[str, float]] = {}
        observed_sources_by_hour: dict[str, set[str]] = {}
        for source_id, samples in (managed_samples_by_source or {}).items():
            for key, value in _positive_deltas_by_hour(samples).items():
                managed_by_hour[key] = managed_by_hour.get(key, 0.0) + value
                source_values = managed_sources_by_hour.setdefault(key, {})
                source_values[source_id] = source_values.get(source_id, 0.0) + value
            for key in _observed_hour_keys(samples):
                observed_sources_by_hour.setdefault(key, set()).add(source_id)

        home_by_hour = _positive_deltas_by_hour(home_samples)
        for key in _observed_hour_keys(home_samples):
            observed_sources_by_hour.setdefault(key, set()).add(home_source_id)
        history = cls()
        source_keys = (
            home_by_hour.keys()
            | managed_by_hour.keys()
            | observed_sources_by_hour.keys()
        )
        for key in source_keys:
            history.buckets[key] = HourlyEnergyBucket(
                hour_start=key,
                home_kwh=home_by_hour.get(key, 0.0),
                managed_kwh=managed_by_hour.get(key, 0.0),
                managed_sources=managed_sources_by_hour.get(key, {}),
                observed_sources=observed_sources_by_hour.get(key, set()),
            )
        return history

    @classmethod
    def from_hourly_energy_changes(
        cls,
        *,
        home_source_id: str,
        home_changes: dict[str, float],
        managed_changes_by_source: dict[str, dict[str, float]],
    ) -> EnergyHistory:
        """Build history from recorder hourly energy change statistics."""
        history = cls()
        for key, value in home_changes.items():
            history.add_hourly_sample(
                datetime.fromisoformat(key),
                home_kwh=value,
                observed_source_ids={home_source_id},
            )
        for source_id, changes in managed_changes_by_source.items():
            for key, value in changes.items():
                history.add_hourly_sample(
                    datetime.fromisoformat(key),
                    home_kwh=0.0,
                    managed_kwh=value,
                    managed_source_id=source_id,
                    observed_source_ids={source_id},
                )
        history.dirty = False
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
        source_entity_id = _source_entity_id(source_type, source_id)
        self.add_hourly_sample(
            timestamp,
            home_kwh=0.0,
            observed_source_ids={source_entity_id},
        )
        previous = self.cumulative_readings.get(source_id)
        delta = 0.0
        if previous:
            delta = value - previous.value
            if delta < 0:
                delta = value

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

    def managed_source_daily_usage(
        self,
        source_id: str,
        *,
        now: datetime,
        learning_days: int,
        minimum_coverage_ratio: float,
    ) -> list[DailyManagedEnergy]:
        """Return complete, coverage-qualified daily totals for one source."""
        cutoff_date = (now - timedelta(days=max(1, learning_days))).date()
        daily_energy: dict[date, float] = {}
        observed_hours: dict[date, set[str]] = {}
        for key, bucket in self.buckets.items():
            bucket_date = datetime.fromisoformat(key).date()
            if bucket_date < cutoff_date or bucket_date >= now.date():
                continue
            daily_energy[bucket_date] = daily_energy.get(bucket_date, 0.0) + (
                bucket.managed_sources.get(source_id, 0.0)
            )
            if source_id in bucket.observed_sources:
                observed_hours.setdefault(bucket_date, set()).add(key)

        result: list[DailyManagedEnergy] = []
        for target_date in sorted(observed_hours):
            expected_hours = _hours_in_local_day(target_date, now)
            observed_count = len(observed_hours[target_date])
            if observed_count < ceil(expected_hours * minimum_coverage_ratio):
                continue
            result.append(
                DailyManagedEnergy(
                    date=target_date,
                    energy_kwh=round(daily_energy.get(target_date, 0.0), 6),
                    observed_hours=observed_count,
                    expected_hours=expected_hours,
                )
            )
        return result

    def has_observations_for_source(self, source_id: str) -> bool:
        return any(
            source_id in bucket.observed_sources for bucket in self.buckets.values()
        )

    def merge_missing_managed_sources(
        self,
        fallback: EnergyHistory,
        source_ids: list[str],
    ) -> None:
        """Fill sources missing from primary history with stored fallback data."""
        for source_id in source_ids:
            if self.has_observations_for_source(source_id):
                continue
            for key, fallback_bucket in fallback.buckets.items():
                value = fallback_bucket.managed_sources.get(source_id, 0.0)
                observed = source_id in fallback_bucket.observed_sources
                if value <= 0 and not observed:
                    continue
                bucket = self.buckets.setdefault(
                    key,
                    HourlyEnergyBucket(hour_start=key),
                )
                if value > 0:
                    bucket.managed_kwh += value
                    bucket.managed_sources[source_id] = value
                if observed:
                    bucket.observed_sources.add(source_id)
            if source_id in fallback.managed_source_totals:
                self.managed_source_totals[source_id] = fallback.managed_source_totals[
                    source_id
                ]

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
            if not bucket.base_usable:
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
            for key, bucket in self.buckets.items()
            if _datetime_sort_value(key) >= _datetime_value(cutoff)
            and bucket.base_usable
        )
        return {
            "bucket_count": len(self.buckets),
            "usable_bucket_count": usable_bucket_count,
            "learning_days": learning_days,
            "has_completed_bucket": any(
                key != hour_key(now) and bucket.base_usable
                for key, bucket in self.buckets.items()
            ),
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
        if delta < 0:
            delta = sample.value
        if delta == 0:
            continue
        key = hour_key(sample.timestamp)
        values[key] = values.get(key, 0.0) + delta
    return values


def _observed_hour_keys(samples: list[CumulativeEnergySample]) -> set[str]:
    if not samples:
        return set()
    ordered = sorted(samples, key=lambda item: item.timestamp)
    first_hour = ordered[0].timestamp.replace(minute=0, second=0, microsecond=0)
    last_hour = ordered[-1].timestamp.replace(minute=0, second=0, microsecond=0)
    keys: set[str] = set()
    current = first_hour
    while current <= last_hour:
        keys.add(hour_key(current))
        current += timedelta(hours=1)
    return keys


def _hours_in_local_day(target_date: date, reference: datetime) -> int:
    start = datetime.combine(target_date, time.min, tzinfo=reference.tzinfo)
    end = datetime.combine(
        target_date + timedelta(days=1),
        time.min,
        tzinfo=reference.tzinfo,
    )
    if reference.tzinfo is None:
        return 24
    return round((end.astimezone(UTC) - start.astimezone(UTC)).total_seconds() / 3600)


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
