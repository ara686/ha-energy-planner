# History Model

The history model intentionally mirrors the active `Energy Prediction 2`
Node-RED flow.

## Inputs

- Home source: hourly utility-meter-like cumulative kWh sensor.
- Managed source: hourly utility-meter-like cumulative kWh sensor.
- Learning window: last 3 days of Home Assistant history.

## Aggregation

For each Home Assistant history state:

1. Parse `state` as kWh.
2. Parse `attributes.last_reset`.
3. Round `last_reset` to the hour.
4. Keep the maximum value seen for that hour.

Managed values are capped at `(3 * 25 * 230) / 1000` kWh before aggregation.

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
