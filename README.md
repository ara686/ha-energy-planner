# ha-energy-planner

Home Assistant custom integration for PV, battery, tariff and EV planning.

The integration calculates energy planning outputs only. It does **not** control Victron, EV chargers, heaters or other devices in v1.

## Main outputs

- `lock_soc`
- `charge_to_soc`
- `safe_discharge_soc`
- `free_capacity_kwh`
- `unused_surplus_kwh`
- compact forecast object

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
