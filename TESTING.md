# Testing Requirements

## Local Quality Gate

Run before a development branch is merged to `develop`:

```bash
uv run --extra ha --extra dev ruff check .
uv run --extra ha --extra dev ruff format --check .
uv run --extra ha --extra dev pytest -q
```

The Home Assistant test extra is required because config flow, options flow,
config entry setup, services, diagnostics and entity behavior are tested against
Home Assistant test helpers.

## Remote Quality Gate

The GitHub Validate workflow must pass on `develop` and release branches:

- Ruff check
- Ruff format check
- pytest with Home Assistant test dependencies
- Hassfest
- HACS Action with category `integration`

## Required Test Coverage

Planner tests:

- normal sunny day, bad solar day, full battery and empty battery
- battery below minimum SoC
- NT across midnight and multiple NT windows
- charge window across midnight
- no Solcast data, malformed Solcast data and missing optional Solcast entities
- managed load subtraction
- history correction
- partial current hour and forecast horizon boundary
- SoC forecast for exactly 24 hours and longer horizons
- SoC forecast using Solcast attributes from HA entities
- `lock_soc`, `charge_to_soc`, `safe_discharge_soc` and unused surplus

Home Assistant integration tests:

- successful Config Flow setup and duplicate prevention
- Options Flow defaults, updates and invalid values
- `async_setup_entry`, `async_unload_entry` and `ConfigEntry.runtime_data`
- DataUpdateCoordinator refresh, update interval and invalid source recovery
- all sensors created with stable unique IDs, translated names, units and device classes
- required-data failure marks dependent sensors unavailable
- main state attributes stay compact and recorder-friendly
- services are registered in `async_setup`, work with loaded entries and raise on missing entries
- diagnostics include useful state without exposing sensitive data

History tests:

- storage load/save
- hourly aggregation
- retention cleanup
- restart persistence
- managed energy subtraction

Legacy Node-RED parity tests:

- keep `nodered_export.json` ignored and out of GitHub
- use only the active flow path that reaches Home Assistant outputs
- ignore backup, archive, dated and disconnected Node-RED branches
- do not copy raw Node-RED code into the integration
- create sanitized parity fixtures or assertions only from understood behavior

## Real Home Assistant Smoke Test

Use this before deploying to production:

- install the public repository as a HACS custom integration repository
- add the integration through the Home Assistant UI
- select real battery, home hourly energy and Solcast forecast entities
- confirm `sensor.energy_planner_state`, `target_soc`, `charge_to_soc` and forecast sensors update
- call `energy_planner.recalculate`
- download diagnostics and check `last_state`, warnings and source entity configuration
- verify Home Assistant logs contain no setup, entity or recorder warnings
