# Options

See `SPECIFICATION.md` for the complete Options Flow field list and defaults.

Important runtime options:

- `update_interval_minutes`: automatic planner polling interval. Battery SoC
  state changes also trigger a debounced recalculation.
- `history_learning_days`: number of Home Assistant history days used to build
  the hour-of-day consumption profile.
- `history_correction_percent`: additional percentage applied to the calculated
  hourly consumption profile.
- `min_baseline_kwh_per_hour`: minimum consumption used when the selected target
  hour has no usable history sample.
- `nt_windows`: low-tariff windows used by tariff-aware planning. Turn off
  **Enable low-tariff windows** in the Options Flow to store an empty list and
  disable tariff windows completely.
