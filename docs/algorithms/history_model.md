# History Model

The history model uses an hour-of-day consumption profile built from internally
maintained hourly energy buckets.

## Inputs

- Home source: cumulative whole-home kWh sensor.
- Managed sources: optional cumulative managed-load kWh sensors.
- Learning window: `history_learning_days`, default 3 days.

## Aggregation

For each configured source:

1. Parse `state` as kWh.
2. Sort history states by timestamp.
3. Convert consecutive cumulative samples into positive deltas.
4. Assign each delta to the hour of the newer sample.

Managed deltas from all managed sources are summed for each hour.

For each home hour:

```text
base_consumption_kwh = max(home_kwh - managed_kwh, 0)
```

The base consumption values are then grouped by hour of day.

```text
hourly_profile[hour] = round(mean(base_consumption for that hour) * 1.05, 2)
```

The planner applies `history_correction_percent` after this profile has been
calculated.

## Forecast Use

For every future slot, use the target slot's hour of day:

```text
slot_hourly_consumption = hourly_profile[target.hour]
```

If the target hour is missing, use `min_baseline_kwh_per_hour`. Do not fall back
to a global average across all hours.
