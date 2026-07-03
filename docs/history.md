# History

Energy Planner follows the active Node-RED flow's hourly consumption model.

The configured home consumption source is expected to be an hourly
utility-meter-like entity whose state is cumulative kWh for the current hour. The
optional managed consumption source uses the same shape.

When Home Assistant history is available, the planner reads the last 3 days for
both sources and builds the load model this way:

1. Use `attributes.last_reset` as the hour key and round it to the hour.
2. Keep the maximum home kWh value for each hour key.
3. Keep the maximum managed kWh value for each hour key, capped at
   `(3 * 25 * 230) / 1000` kWh.
4. Subtract managed kWh from home kWh for the same hour key.
5. Group the resulting base consumption by hour of day.
6. Average each hour-of-day group and apply the legacy 5% margin.

Forecast slots use that hour-of-day profile. A forecast slot at 11:00 uses the
average of historical 11:00 values from the learning window. It does not use a
global average of all historical consumption. If there is no sample for the
target hour, the slot uses `min_baseline_kwh_per_hour`.

The Options Flow `history_correction_percent` is applied after the hourly profile
is calculated, matching the active Node-RED flow's `input_number.history_correction`
behavior.

Energy Planner also keeps its own storage-backed hourly history as a fallback.
On each planner refresh the fallback history stores only the delta since the
previous reading in the same hour. When the utility meter resets for a new hour,
a new history bucket is started.
