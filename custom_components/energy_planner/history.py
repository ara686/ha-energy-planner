from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

STORAGE_VERSION = 1


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
class EnergyHistory:
    buckets: dict[str, HourlyEnergyBucket] = field(default_factory=dict)

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

    def average_base_consumption_kwh_per_hour(
        self,
        *,
        now: datetime,
        learning_days: int,
        min_baseline_kwh_per_hour: float,
    ) -> float:
        cutoff = now - timedelta(days=max(1, learning_days))
        values = [
            bucket.base_kwh
            for key, bucket in self.buckets.items()
            if datetime.fromisoformat(key) >= cutoff
        ]
        if not values:
            return min_baseline_kwh_per_hour
        return max(sum(values) / len(values), min_baseline_kwh_per_hour)

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
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "buckets": [
                bucket.as_dict()
                for bucket in sorted(
                    self.buckets.values(),
                    key=lambda item: item.hour_start,
                )
            ]
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
        return cls(buckets=buckets)


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
