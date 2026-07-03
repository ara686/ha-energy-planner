from __future__ import annotations

from datetime import datetime, timedelta

from custom_components.energy_planner.history import EnergyHistory, hour_key


def test_hourly_aggregation_and_managed_subtraction():
    history = EnergyHistory()
    timestamp = datetime(2026, 7, 3, 10, 15)

    history.add_hourly_sample(timestamp, home_kwh=1.5, managed_kwh=0.4)
    history.add_hourly_sample(timestamp + timedelta(minutes=20), home_kwh=0.5)

    key = hour_key(timestamp)
    assert history.buckets[key].home_kwh == 2.0
    assert history.buckets[key].managed_kwh == 0.4
    assert history.base_consumption_for_hour(key) == 1.6


def test_managed_subtraction_never_returns_negative_base_consumption():
    history = EnergyHistory()
    timestamp = datetime(2026, 7, 3, 10, 0)

    history.add_hourly_sample(timestamp, home_kwh=0.5, managed_kwh=1.5)

    assert history.base_consumption_for_hour(hour_key(timestamp)) == 0.0


def test_cleanup_removes_buckets_outside_retention():
    now = datetime(2026, 7, 3, 12, 0)
    history = EnergyHistory()
    history.add_hourly_sample(now - timedelta(days=2), home_kwh=1.0)
    history.add_hourly_sample(now - timedelta(hours=12), home_kwh=2.0)

    history.cleanup(now=now, retention_days=1)

    assert len(history.buckets) == 1
    assert history.base_consumption_for_hour(hour_key(now - timedelta(hours=12))) == 2.0


def test_history_roundtrip_survives_restart_serialization():
    history = EnergyHistory()
    timestamp = datetime(2026, 7, 3, 10, 0)
    history.record_cumulative_hourly_source(timestamp, source="home", value=1.2)
    history.record_cumulative_hourly_source(timestamp, source="managed", value=0.2)

    restored = EnergyHistory.from_dict(history.as_dict())

    assert restored.as_dict() == history.as_dict()
    assert restored.base_consumption_for_hour(hour_key(timestamp)) == 1.0
    assert restored.cumulative_readings["home"].value == 1.2


def test_cumulative_hourly_source_records_only_deltas_within_hour():
    history = EnergyHistory()
    timestamp = datetime(2026, 7, 3, 10, 5)

    history.record_cumulative_hourly_source(timestamp, source="home", value=0.4)
    history.record_cumulative_hourly_source(
        timestamp + timedelta(minutes=10),
        source="home",
        value=0.7,
    )
    history.record_cumulative_hourly_source(
        timestamp + timedelta(minutes=20),
        source="home",
        value=0.7,
    )

    assert history.base_consumption_for_hour(hour_key(timestamp)) == 0.7


def test_cumulative_hourly_source_starts_new_bucket_after_meter_reset():
    history = EnergyHistory()
    timestamp = datetime(2026, 7, 3, 10, 55)

    history.record_cumulative_hourly_source(timestamp, source="home", value=1.2)
    history.record_cumulative_hourly_source(
        timestamp + timedelta(minutes=10),
        source="home",
        value=0.2,
    )

    assert history.base_consumption_for_hour(hour_key(timestamp)) == 1.2
    assert (
        history.base_consumption_for_hour(hour_key(timestamp + timedelta(hours=1)))
        == 0.2
    )


def test_predicted_base_consumption_prefers_same_hour_history():
    now = datetime(2026, 7, 3, 12, 0)
    target = datetime(2026, 7, 3, 18, 0)
    history = EnergyHistory()
    history.add_hourly_sample(datetime(2026, 7, 2, 18, 0), home_kwh=2.0)
    history.add_hourly_sample(datetime(2026, 7, 1, 18, 0), home_kwh=1.0)
    history.add_hourly_sample(now - timedelta(hours=1), home_kwh=10.0)

    assert (
        history.predicted_base_consumption_kwh_per_hour(
            now=now,
            target=target,
            learning_days=3,
            min_baseline_kwh_per_hour=0.2,
        )
        == 1.5
    )


def test_average_base_consumption_uses_learning_window_and_minimum():
    now = datetime(2026, 7, 3, 12, 0)
    history = EnergyHistory()
    history.add_hourly_sample(now - timedelta(days=5), home_kwh=10.0)
    history.add_hourly_sample(now - timedelta(hours=2), home_kwh=0.1)
    history.add_hourly_sample(now - timedelta(hours=1), home_kwh=0.3)

    assert (
        history.average_base_consumption_kwh_per_hour(
            now=now,
            learning_days=1,
            min_baseline_kwh_per_hour=0.25,
        )
        == 0.25
    )


def test_history_status_reports_usable_bucket_count():
    now = datetime(2026, 7, 3, 12, 0)
    history = EnergyHistory()
    history.add_hourly_sample(now - timedelta(days=3), home_kwh=1.0)
    history.add_hourly_sample(now - timedelta(hours=1), home_kwh=1.0)

    assert history.status(now=now, learning_days=1) == {
        "bucket_count": 2,
        "usable_bucket_count": 1,
        "learning_days": 1,
        "has_completed_bucket": True,
    }
