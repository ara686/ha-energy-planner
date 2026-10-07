# Planner CPU validation

The planner preserves the configured horizon, slot resolution, energy constraints
and 18-step allocation search. This change reduces work per trial and coalesces
source requests; it does not turn off event-driven recalculation.

## Simulation changes

- Solar-reserve checks prepare normalized slots and tariff flags once, keep
  unrounded battery state, and replay from the changed slot. They compare grid
  consumption using the same millikWh rounding and tolerance as the public
  forecast. Rejected trials stop at the first budget violation without building
  forecast points or projected horizon endpoints.
- Joint-plan trials cache per-slot powers, durations, tariffs and output metadata.
  They replay from the changed slot, reject violations immediately, and reuse the
  remaining trajectory once the exact battery state converges. Thermal limits,
  the house's fixed charging budget and minimum EV current remain enforced.
- Prepared state is local to one calculation. Changed configuration, source
  values and forecast inputs are read again on subsequent updates. Planning
  continues to run in Home Assistant's executor.

## Reproduce the benchmark

From the repository root, with the trusted release tag available locally:

```bash
uv run --extra ha --extra dev python scripts/benchmark_planner.py --baseline v0.1.33 --repeat 3
```

The benchmark loads the original implementations from the local Git revision
without changing the checkout. It compares complete results on each repetition
and fails on a difference. The workload has 576 five-minute slots over 48 hours,
a 24 kWh battery, two daily low-tariff windows, solar generation and a 300 litre,
3 kW hot-water tank with thermal losses and daily demand.

Example local measurement on 2026-10-07, median of three runs:

| Calculation | v0.1.33 | Optimized | Speedup |
| --- | ---: | ---: | ---: |
| Direct-solar reserve allocation | 0.496 s | 0.034 s | 14.4× |
| Joint plan with hot water | 1.773 s | 0.049 s | 35.9× |

Outputs matched exactly. These are timings for two calculation paths on the
local development machine, not total Home Assistant CPU measurements. Actual
runtime depends on hardware, demand and forecast inputs. A running calculation
can still occupy one CPU core; the optimization reduces its duration.

Regression tests compare optimized trials against full-horizon forecasts and
replays, including changing tariffs, limited power, existing managed demand,
thermal limits, EVs and the repeated DST hour. Deterministic work-bound tests
verify that unaffected segments are reused without flaky wall-clock assertions.

## Recalculation timing and diagnostics

Battery SoC and managed cumulative-energy changes retain a 60-second delay;
EV model changes retain a 10-second delay. All sources share one earliest-deadline
queue. A faster source refresh, periodic poll, manual service or EV-boundary
refresh consumes all preceding pending changes. Continuous input events cannot
postpone the deadline. Changes arriving during calculation remain pending for
one subsequent refresh; unload cancels pending work.

The configured polling interval and EV start/end boundary timers remain active.
A source change can therefore still trigger a calculation before the configured
polling interval expires.

Download integration diagnostics and inspect `last_refresh`:

- `reasons`: `setup`, `periodic`, `manual`, `ev_boundary`, `battery_soc`,
  `managed_energy` or `ev_model`; merged requests list all consumed source reasons.
- `duration_seconds`: elapsed time including input/history retrieval and planning.
- `success`: whether that data update completed successfully.

The same summary appears at debug log level. Check it alongside CPU measurements
when testing the new version on a real Home Assistant installation.
