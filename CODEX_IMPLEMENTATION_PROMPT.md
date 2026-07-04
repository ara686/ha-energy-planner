# Codex Implementation Prompt

You are implementing `ha-energy-planner`, a Home Assistant custom integration.

## Objective

Create a production-quality custom integration named `energy_planner`.

It calculates energy planning outputs from configured Home Assistant entities
and exposes planner entities only.

Do not control Victron, EV chargers, heaters, pumps or other devices in v1.

All runtime data must be read from configured Home Assistant entities, states and attributes.
Do not call Solcast, Victron, tariff provider or device APIs directly in v1.

## Must follow

- Official Home Assistant custom integration patterns.
- Current Home Assistant Developer documentation.
- Current HACS publishing and validation requirements.
- Config Flow.
- Options Flow.
- DataUpdateCoordinator.
- Diagnostics.
- Services.
- Tests.
- HACS compatibility.
- No YAML setup.
- No blocking I/O.
- No recorder internals as required dependency.

## Home Assistant implementation rules

- Use config entries only for setup.
- Keep persistent setup fields in `ConfigEntry.data`.
- Keep user-tunable runtime settings in `ConfigEntry.options`.
- Keep runtime objects in typed `ConfigEntry.runtime_data`.
- Implement setup and unload cleanly with `async_setup_entry` and `async_unload_entry`.
- Await `hass.config_entries.async_forward_entry_setups` when forwarding platforms.
- Use `DataUpdateCoordinator` as the shared update point and validate setup with `async_config_entry_first_refresh`.
- Use `ConfigEntryNotReady` for temporary setup failures.
- Prevent duplicate planner instances.
- Mark entities unavailable for invalid or missing required data.
- Give entities stable unique IDs, `_attr_has_entity_name = True`, translated names and correct device classes, state classes and native units.
- Keep normal entity attributes compact; move large debug data to diagnostics or export services.
- Register services in `async_setup`, validate input and raise proper Home Assistant exceptions.
- Keep all blocking I/O and expensive work out of the event loop.
- Re-check current Home Assistant stable and beta/pre-release compatibility before release-oriented changes.

## HACS implementation rules

- Preserve the standard HACS integration repository layout:

```text
custom_components/energy_planner/manifest.json
README.md
hacs.json
```

- Keep `hacs.json` in the repository root with an honest minimum supported Home Assistant version.
- Keep the integration manifest HACS-compatible with `domain`, `documentation`, `issue_tracker`, `codeowners`, `name` and `version`.
- Keep `manifest.json` `version` synchronized with release intent.
- Maintain user-facing README installation, configuration, entity, service and troubleshooting documentation.
- Add brand assets before publishing through HACS.
- Validate release candidates with pytest, Ruff, Hassfest and HACS Action for category `integration`.
- Publish full GitHub releases for HACS releases; tags alone are not enough.

## Repository reference

Use the project `ha-chmi-weather` as style/reference for:
- repository organization
- tests
- CI
- linting
- HACS metadata
- AGENTS.md conventions

## Implement by waves

Follow `IMPLEMENTATION_PLAN.md`.

Do not jump directly to all features.

## Development workflow

Use `develop` as the development integration branch.

For each implementation task:

- create a dedicated branch based on `develop`
- implement and test the change on that branch
- merge the branch back into `develop` only after tests pass

Keep `main` stable and release-ready.

## Key files to create

```text
custom_components/energy_planner/__init__.py
custom_components/energy_planner/manifest.json
custom_components/energy_planner/const.py
custom_components/energy_planner/config_flow.py
custom_components/energy_planner/coordinator.py
custom_components/energy_planner/diagnostics.py
custom_components/energy_planner/history.py
custom_components/energy_planner/models.py
custom_components/energy_planner/planner.py
custom_components/energy_planner/sensor.py
custom_components/energy_planner/services.yaml
custom_components/energy_planner/strings.json
custom_components/energy_planner/translations/cs.json
custom_components/energy_planner/translations/en.json
```

## Planner core

Planner core must accept plain Python input models and return plain Python result models.

Planner output must include:

- `lock_soc`
- `charge_to_soc`
- `target_soc`
- `safe_discharge_soc`
- `free_capacity_soc`
- `free_capacity_kwh`
- `unused_surplus_kwh`
- `unused_surplus_kwh_total`
- `first_full_time`
- `vt_grid_import_kwh_at_target`
- `charged_kwh_total_at_target`
- `soc_at_planner_start`
- `kwh_at_planner_start`
- `lock_start`
- `sun_start`
- `soc_at_lock_start`
- `kwh_at_lock_start`
- `vt_peak_deficit_kwh_from_lock_start`
- `soc_forecast`
- `soc_forecast_24h`
- `soc_at_forecast_horizon`

## Algorithm

Use 5-minute slots by default.

Rules:

- Battery covers load by default.
- Simulate battery SoC for at least the next 24 hours.
- Support longer SoC prediction through the configurable `forecast_horizon_hours`.
- Use Solcast forecast data only from configured Home Assistant entities and attributes.
- Use Home Assistant history-derived baseline consumption as the load input.
- In NT, prefer grid and preserve battery lock.
- In VT, use battery normally down to physical floor.
- Physical floor is current battery minimum SoC.
- `lock_soc` is based on peak VT deficit from `lock_start` to `sun_start`.
- `sun_start` is the first time PV covers consumption continuously for configured minutes.
- `charge_to_soc` is the lowest target that avoids VT floor deficit when charging only in charge window.
- `safe_discharge_soc` is the lowest current SoC that can be allowed while avoiding VT grid import.
- `unused_surplus_kwh` is PV energy that cannot be stored due to full battery.
- `soc_forecast` is a compact time series of timestamp, predicted SoC percent and predicted battery kWh over the forecast horizon.
- `soc_forecast_24h` must be present even when the configured horizon is longer than 24 hours.

## Sensors

Implement all sensors listed in `SPECIFICATION.md`.

## History

Implement internal history using Home Assistant storage.

Do not require recorder internals.

## Tests

Implement tests described in `TESTING.md`.

The planner tests are highest priority and must be deterministic.

## Acceptance criteria

- Integration can be added from UI.
- All tests pass.
- Planner core has no HA imports.
- Coordinator handles missing inputs gracefully.
- Sensors expose correct units/classes.
- Documentation explains current behavior, setup, entities, services and troubleshooting.
