# History

Energy Planner uses an hour-of-day consumption model built internally from
cumulative energy source sensors.

The configured home consumption source is expected to be a cumulative kWh sensor
for whole-home consumption. Optional managed consumption sources use the same
shape and may contain zero, one or many entities.

When Home Assistant history is available, the planner reads the configured
`history_learning_days` window and builds the load model this way:

1. Parse each source state as cumulative kWh.
2. Sort samples by timestamp.
3. Convert consecutive samples into positive deltas.
4. Assign each delta to the hour of the newer sample.
5. Store managed deltas both per source and as a combined managed total for
   each hour.
6. Subtract combined managed kWh from home kWh for the same hour key.
7. Mark the bucket usable for baseline calculation only when the home energy
   source has a positive value and is not lower than the managed total.
8. Group usable base consumption by hour of day.
9. Average each hour-of-day group and apply the built-in 5% history margin.

Forecast slots use that hour-of-day profile. A forecast slot at 11:00 uses the
average of historical 11:00 values from the learning window. It does not use a
global average of all historical consumption. If there is no sample for the
target hour, the slot uses `min_baseline_kwh_per_hour`.

Managed-only buckets are kept in history for dashboards and per-load statistics,
but they are not used as zero home consumption. This matters during the first
days after setup or after changing source entities: if Home Assistant has managed
load history but the selected home energy source did not yet have matching
history, the planner waits for usable home buckets instead of averaging in
artificial zeros.

The Options Flow `history_correction_percent` is applied after the hourly profile
is calculated.

Energy Planner also keeps its own storage-backed hourly history as a fallback.
State changes of the configured energy source sensors are recorded as positive
cumulative deltas. The first reading is kept only as a baseline.

Per-source managed history is stored in the same hourly buckets. For example,
one bucket can contain:

```text
home_kwh = 4.2
managed_kwh = 1.7
managed_sources.sensor.ev_energy_total = 1.2
managed_sources.sensor.water_heater_energy_total = 0.5
base_kwh = 2.5
base_usable = true
```

The planner still uses the combined `managed_kwh` value for baseline
calculation. The per-source values are exposed for dashboards, statistics and
automation conditions.

The main `sensor.energy_planner_consumption_history` graph payload is kept
compact for Home Assistant's recorder. It exposes hourly `home_kwh`,
`managed_kwh`, `base_kwh` and usability flags. Per-source history is available
through the disabled-by-default `sensor.energy_planner_managed_<source>_history`
entities.
