# Implementation Plan

## Wave 0 – repository bootstrap

- Create integration skeleton.
- Add manifest.
- Add HACS metadata.
- Add README.
- Add AGENTS.md, SKILL.md, SPECIFICATION.md.
- Add CI.
- Add placeholder config flow.
- Add one state sensor.

Acceptance:
- Home Assistant loads the integration.
- Tests run.

## Wave 1 – pure planner engine

- Implement typed models.
- Implement slot generation.
- Implement tariff window handling.
- Implement SoC simulation.
- Implement `lock_soc`.
- Implement `charge_to_soc`.
- Implement `safe_discharge_soc`.
- Implement surplus calculation.

Acceptance:
- planner tests pass with frozen time.
- no HA imports in planner code.

## Wave 2 – coordinator and entity parsing

- Read configured input entities.
- Parse battery values.
- Parse Solcast detailed hourly attributes.
- Parse tariff/price entity if present.
- Fallback to UI NT windows.

Acceptance:
- coordinator returns planner result.
- missing optional data creates warnings, not crashes.

## Wave 3 – internal history

- Implement HA storage backed history.
- Hourly bucket aggregation.
- Managed load subtraction.
- Retention cleanup.
- History status.

Acceptance:
- history survives restart.
- tests cover retention and bucket aggregation.

## Wave 4 – sensors

- Add all output sensors.
- Use correct units/device classes.
- Add compact forecast attributes.
- Add availability rules.

Acceptance:
- all expected sensors appear under one device.

## Wave 5 – options flow

- Expose all tuning parameters.
- Validate NT and charge windows.
- Validate interval.
- Recalculate after option update.

Acceptance:
- all runtime behavior can be changed from UI.

## Wave 6 – services and diagnostics

- Add `energy_planner.recalculate`.
- Add `energy_planner.export_debug`.
- Add diagnostics.
- Add repairs issue for insufficient data.

Acceptance:
- manual recalc works.
- diagnostics include useful state.

## Wave 7 – planner validation

- Add fixture from documented reference behavior.
- Compare expected outputs.
- Document differences.
- Keep raw external automation exports out of GitHub.
- Keep fixtures sanitized and deterministic.

Acceptance:
- README explains current behavior, setup, entities and troubleshooting.
