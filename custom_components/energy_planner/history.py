from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
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

    @property
    def base_kwh(self) -> float:
        return max(self.home_kwh - self.managed_kwh, 0.0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "hour_start": self.hour_start,
            "home_kwh": round(self.home_kwh, 6),
            "managed_kwh": round(self.managed_kwh, 6),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HourlyEnergyBucket:
        return cls(
            hour_start=str(data["hour_start"]),
            home_kwh=float(data.get("home_kwh", 0.0)),
            managed_kwh=float(data.get("managed_kwh", 0.0)),
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

    def add_hourly_sample(
        self,
        timestamp: datetime,
        *,
        home_kwh: float,
        managed_kwh: float = 0.0,
    ) -> None:
        key = hour_key(timestamp)
        bucket = self.buckets.setdefault(key, HourlyEnergyBucket(hour_start=key))
        bucket.home_kwh += max(home_kwh, 0.0)
        bucket.managed_kwh += max(managed_kwh, 0.0)

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
                "base_kwh": round(bucket.base_kwh, 6),
                "is_current_hour": bucket.hour_start == current_key,
            }
            for key, bucket in sorted(self.buckets.items())
            if datetime.fromisoformat(key) >= cutoff
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
        for samples in (managed_samples_by_source or {}).values():
            for key, value in _positive_deltas_by_hour(samples).items():
                managed_by_hour[key] = managed_by_hour.get(key, 0.0) + value

        home_by_hour = _positive_deltas_by_hour(home_samples)
        history = cls()
        for key, home_kwh in home_by_hour.items():
            history.buckets[key] = HourlyEnergyBucket(
                hour_start=key,
                home_kwh=home_kwh,
                managed_kwh=managed_by_hour.get(key, 0.0),
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

        self.cumulative_readings[source_id] = CumulativeHourlyReading(
            hour_start=key,
            value=value,
        )

        if delta <= 0:
            return
        if source_type == "home":
            self.add_hourly_sample(timestamp, home_kwh=delta)
        elif source_type == "managed":
            self.add_hourly_sample(timestamp, home_kwh=0.0, managed_kwh=delta)

    def average_base_consumption_kwh_per_hour(
        self,
        *,
        now: datetime,
        learning_days: int,
        min_baseline_kwh_per_hour: float,
        include_current_hour: bool = True,
    ) -> float:
        cutoff = now - timedelta(days=max(1, learning_days))
        current_key = hour_key(now)
        values = [
            bucket.base_kwh
            for key, bucket in self.buckets.items()
            if datetime.fromisoformat(key) >= cutoff
            and (include_current_hour or key != current_key)
        ]
        if not values:
            return min_baseline_kwh_per_hour
        return max(sum(values) / len(values), min_baseline_kwh_per_hour)

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
            if bucket_time < cutoff:
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

    def predicted_base_consumption_kwh_per_hour(
        self,
        *,
        now: datetime,
        target: datetime,
        learning_days: int,
        min_baseline_kwh_per_hour: float,
        margin_percent: float = 0.0,
        correction_percent: float = 0.0,
    ) -> float:
        """Predict consumption for a future hour from stored history."""
        profile = self.hourly_base_consumption_profile(
            now=now,
            learning_days=learning_days,
            margin_percent=margin_percent,
        )
        value = profile.get(target.hour, 0.0)
        value *= 1 + correction_percent / 100
        return max(value, min_baseline_kwh_per_hour)

    def cleanup(self, *, now: datetime, retention_days: int) -> None:
        cutoff = now - timedelta(days=max(1, retention_days))
        self.buckets = {
            key: bucket
            for key, bucket in self.buckets.items()
            if datetime.fromisoformat(key) >= cutoff
        }

    def status(self, *, now: datetime, learning_days: int) -> dict[str, Any]:
        cutoff = now - timedelta(days=max(1, learning_days))
        usable_bucket_count = sum(
            1 for key in self.buckets if datetime.fromisoformat(key) >= cutoff
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
                    key=lambda item: item.hour_start,
                )
            ],
            "cumulative_readings": {
                source: reading.as_dict()
                for source, reading in sorted(self.cumulative_readings.items())
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
        return cls(buckets=buckets, cumulative_readings=cumulative_readings)


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


def hour_key(timestamp: datetime) -> str:
    return timestamp.replace(minute=0, second=0, microsecond=0).isoformat()


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
