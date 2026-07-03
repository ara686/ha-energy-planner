# Options

See `SPECIFICATION.md` for the complete Options Flow field list and defaults.

Important history-related options:

- `history_correction_percent`: additional percentage applied to the calculated
  hourly consumption profile. Set this to the same value as the legacy
  `input_number.history_correction` when comparing with Node-RED.
- `min_baseline_kwh_per_hour`: minimum consumption used when the selected target
  hour has no usable history sample.
