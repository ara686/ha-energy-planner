# ha-energy-planner

Home Assistant custom integration for PV, battery, tariff and EV planning.

> [!WARNING]
> Energy Planner is experimental software under active development. It is not recommended for production use. Install and use it at your own risk, and do not rely on it for safety-critical, life-critical, property protection, emergency, operational, financial, billing, regulatory, or compliance decisions.

The integration calculates energy planning outputs only. It does **not** control Victron, EV chargers, heaters or other devices in v1.
If you use its sensors in automations, you are responsible for validating the
automation behavior and all consequences of those automations.

## Installation

HACS custom repository:

1. Add `https://github.com/ara686/ha-energy-planner` as an Integration custom repository.
2. Install Energy Planner through HACS.
3. Restart Home Assistant.
4. Add the integration from Settings > Devices & services.

Manual installation:

1. Copy `custom_components/energy_planner` into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Add the integration from the UI.

YAML setup is intentionally not supported in v1.

## Configuration

Required Home Assistant entities:

- battery SoC in percent
- battery capacity in kWh
- battery minimum SoC in percent
- home hourly consumption history source in kWh

Optional Home Assistant entities:

- managed hourly consumption history source in kWh
- Solcast today forecast entity
- Solcast tomorrow forecast entity
- price or tariff entity

Solcast data is read from Home Assistant entity attributes. The integration does
not call Solcast directly.

Runtime behavior is changed through the Options Flow: planning interval, baseline
load, grid charge limits, NT windows, charge window and forecast horizon.

The home consumption source is expected to be an hourly utility-meter-like entity
whose state is cumulative kWh for the current hour. Energy Planner stores its own
hourly history from that entity after installation and uses that history to
predict future consumption. It does not require Home Assistant recorder internals
and it does not backfill old recorder data in v1.

## Main outputs

- `lock_soc`
- `charge_to_soc`
- `safe_discharge_soc`
- `free_capacity_kwh`
- `unused_surplus_kwh`
- compact forecast object

The forecast includes at least 24 hours and can use a longer configured horizon
when Home Assistant source data is available.

## Services

- `energy_planner.recalculate` refreshes planner data for loaded entries.
- `energy_planner.export_debug` writes compact debug data to the log and fires an
  `energy_planner_debug_exported` event.

The services do not control devices.

## Troubleshooting

- `insufficient_data` means a required source entity is missing, unavailable or
  not numeric.
- `warning` usually means optional data, such as Solcast forecast, is missing or
  malformed.
- Use diagnostics from the integration page to inspect configured entities, last
  planner state, warnings and plan summary.
- Keep debug payloads out of regular state attributes; use diagnostics or
  `energy_planner.export_debug`.

## Development Validation

```bash
uv run --extra ha --extra dev ruff check .
uv run --extra ha --extra dev ruff format --check .
uv run --extra ha --extra dev pytest -q
```

Release candidates must also pass Hassfest and the HACS Action in GitHub Actions.

## Migration from Node-RED

This integration replaces the active `Energy Prediction 2` Node-RED flow with a
tested Home Assistant integration.

Only the active Node-RED calculation path is used as a parity reference. Backup,
dated archive and disconnected Node-RED nodes are ignored.

The local `nodered_export.json` file is intentionally ignored by Git and must not
be published. Parity tests use sanitized fixtures derived from understood active
flow behavior, not raw Node-RED code.

Important migration notes:

- v1 exposes planner sensors only and does not control devices.
- `lock_soc` preserves the battery reserve for NT/VT planning.
- `charge_to_soc` is the optional grid-charge target for the configured charge window.
- `free_capacity_kwh` means safely dischargeable energy above `safe_discharge_soc`.
- The legacy flow adds 1 percentage point to the configured battery minimum SoC before using it as its effective floor; parity fixtures model that explicitly.
- The pure planner may expose cleaner timestamp formatting and compact forecast attributes while preserving the core planning outputs.

See `SPECIFICATION.md` and `CODEX_IMPLEMENTATION_PROMPT.md`.

## Disclaimer

This software is provided as-is, without warranty, and without a support
guarantee. See `DISCLAIMER.md` for project risk and support limitations.
