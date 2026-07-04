from __future__ import annotations

from datetime import datetime, timedelta

from custom_components.energy_planner.history import (
    CumulativeEnergySample,
    EnergyHistory,
    hour_key,
)


def test_hourly_aggregation_and_managed_subtraction():
    history = EnergyHistory()
    timestamp = datetime(2026, 7, 3, 10, 15)

    history.add_hourly_sample(timestamp, home_kwh=1.5, managed_kwh=0.4)
    history.add_hourly_sample(timestamp + timedelta(minutes=20), home_kwh=0.5)

    key = hour_key(timestamp)
    assert history.buckets[key].home_kwh == 2.0
    assert history.buckets[key].managed_kwh == 0.4
    assert history.base_consumption_for_hour(key) == 1.6


def test_hourly_points_export_home_managed_and_base_consumption():
    now = datetime(2026, 7, 3, 12, 0)
    history = EnergyHistory()
    history.add_hourly_sample(now - timedelta(hours=2), home_kwh=2.0, managed_kwh=0.5)
    history.add_hourly_sample(now - timedelta(hours=1), home_kwh=1.25)
    history.add_hourly_sample(now - timedelta(days=5), home_kwh=9.0)

    points, truncated = history.hourly_points(
        now=now,
        learning_days=3,
        point_limit=10,
    )

    assert not truncated
    assert points == [
        {
            "timestamp": "2026-07-03T10:00:00",
            "home_kwh": 2.0,
            "managed_kwh": 0.5,
            "base_kwh": 1.5,
            "is_current_hour": False,
        },
        {
            "timestamp": "2026-07-03T11:00:00",
            "home_kwh": 1.25,
            "managed_kwh": 0.0,
            "base_kwh": 1.25,
            "is_current_hour": False,
        },
    ]

    limited_points, limited_truncated = history.hourly_points(
        now=now,
        learning_days=3,
        point_limit=1,
    )

    assert limited_truncated
    assert limited_points == [points[-1]]


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
    history.record_cumulative_energy_source(
        timestamp,
        source_type="home",
        source_id="home:sensor.home_energy_total",
        value=10.0,
    )
    history.record_cumulative_energy_source(
        timestamp + timedelta(minutes=10),
        source_type="home",
        source_id="home:sensor.home_energy_total",
        value=11.2,
    )
    history.record_cumulative_energy_source(
        timestamp,
        source_type="managed",
        source_id="managed:sensor.ev_energy_total",
        value=5.0,
    )
    history.record_cumulative_energy_source(
        timestamp + timedelta(minutes=10),
        source_type="managed",
        source_id="managed:sensor.ev_energy_total",
        value=5.2,
    )

    restored = EnergyHistory.from_dict(history.as_dict())

    assert restored.as_dict() == history.as_dict()
    assert restored.base_consumption_for_hour(hour_key(timestamp)) == 1.0
    assert restored.cumulative_readings["home:sensor.home_energy_total"].value == 11.2


def test_cumulative_energy_source_records_only_positive_deltas():
    history = EnergyHistory()
    timestamp = datetime(2026, 7, 3, 10, 5)

    history.record_cumulative_energy_source(
        timestamp,
        source_type="home",
        source_id="home:sensor.home_energy_total",
        value=100.4,
    )
    history.record_cumulative_energy_source(
        timestamp + timedelta(minutes=10),
        source_type="home",
        source_id="home:sensor.home_energy_total",
        value=100.7,
    )
    history.record_cumulative_energy_source(
        timestamp + timedelta(minutes=20),
        source_type="home",
        source_id="home:sensor.home_energy_total",
        value=100.7,
    )

    assert round(history.base_consumption_for_hour(hour_key(timestamp)), 6) == 0.3


def test_cumulative_energy_source_assigns_cross_hour_delta_to_new_hour():
    history = EnergyHistory()
    timestamp = datetime(2026, 7, 3, 10, 55)

    history.record_cumulative_energy_source(
        timestamp,
        source_type="home",
        source_id="home:sensor.home_energy_total",
        value=100.0,
    )
    history.record_cumulative_energy_source(
        timestamp + timedelta(minutes=10),
        source_type="home",
        source_id="home:sensor.home_energy_total",
        value=100.2,
    )

    assert history.base_consumption_for_hour(hour_key(timestamp)) == 0.0
    assert (
        round(
            history.base_consumption_for_hour(hour_key(timestamp + timedelta(hours=1))),
            6,
        )
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


def test_predicted_base_consumption_falls_back_to_minimum_for_missing_hour():
    now = datetime(2026, 7, 3, 12, 0)
    target = datetime(2026, 7, 3, 18, 0)
    history = EnergyHistory()
    history.add_hourly_sample(now - timedelta(hours=1), home_kwh=10.0)

    assert (
        history.predicted_base_consumption_kwh_per_hour(
            now=now,
            target=target,
            learning_days=3,
            min_baseline_kwh_per_hour=0.2,
        )
        == 0.2
    )


def test_cumulative_history_samples_build_nodered_hourly_profile():
    now = datetime(2026, 7, 3, 12, 0)
    history = EnergyHistory.from_cumulative_energy_samples(
        home_samples=[
            CumulativeEnergySample(datetime(2026, 7, 1, 10, 55), 10.0),
            CumulativeEnergySample(datetime(2026, 7, 1, 11, 10), 11.8),
            CumulativeEnergySample(datetime(2026, 7, 1, 11, 50), 12.0),
            CumulativeEnergySample(datetime(2026, 7, 2, 10, 55), 20.0),
            CumulativeEnergySample(datetime(2026, 7, 2, 11, 30), 24.0),
            CumulativeEnergySample(datetime(2026, 7, 2, 11, 55), 24.0),
            CumulativeEnergySample(datetime(2026, 7, 2, 12, 10), 34.0),
        ],
        managed_samples_by_source={
            "sensor.ev_energy_total": [
                CumulativeEnergySample(datetime(2026, 7, 1, 10, 55), 0.0),
                CumulativeEnergySample(datetime(2026, 7, 1, 11, 20), 0.5),
                CumulativeEnergySample(datetime(2026, 7, 2, 10, 55), 10.0),
                CumulativeEnergySample(datetime(2026, 7, 2, 11, 20), 11.0),
            ],
        },
    )

    profile = history.hourly_base_consumption_profile(
        now=now,
        learning_days=3,
        margin_percent=5,
    )

    assert history.base_consumption_for_hour("2026-07-01T11:00:00") == 1.5
    assert history.base_consumption_for_hour("2026-07-02T11:00:00") == 3.0
    assert profile[11] == 2.36
    assert profile[12] == 10.5


def test_multiple_managed_energy_sources_are_summed_by_hour():
    history = EnergyHistory.from_cumulative_energy_samples(
        home_samples=[
            CumulativeEnergySample(datetime(2026, 7, 1, 10, 55), 10.0),
            CumulativeEnergySample(datetime(2026, 7, 1, 11, 30), 20.0),
        ],
        managed_samples_by_source={
            "sensor.ev_energy_total": [
                CumulativeEnergySample(datetime(2026, 7, 1, 10, 55), 0.0),
                CumulativeEnergySample(datetime(2026, 7, 1, 11, 30), 2.0),
            ],
            "sensor.water_heater_energy_total": [
                CumulativeEnergySample(datetime(2026, 7, 1, 10, 55), 10.0),
                CumulativeEnergySample(datetime(2026, 7, 1, 11, 30), 13.0),
            ],
        },
    )

    assert history.buckets["2026-07-01T11:00:00"].managed_kwh == 5.0
    assert history.base_consumption_for_hour("2026-07-01T11:00:00") == 5.0


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
