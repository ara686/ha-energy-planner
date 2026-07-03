# Home Assistant and HACS Quality Gate

This project follows the current Home Assistant Developer documentation and HACS
publishing documentation as the source of truth.

Reference documentation:

- Home Assistant integration manifest: https://developers.home-assistant.io/docs/creating_integration_manifest/
- Home Assistant config entries: https://developers.home-assistant.io/docs/config_entries_index/
- Home Assistant config flow: https://developers.home-assistant.io/docs/core/integration/config_flow/
- Home Assistant fetching data: https://developers.home-assistant.io/docs/integration_fetching_data/
- Home Assistant entities: https://developers.home-assistant.io/docs/core/entity/
- Home Assistant testing: https://developers.home-assistant.io/docs/development_testing/
- Home Assistant integration quality rules: https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/
- HACS publishing requirements: https://www.hacs.xyz/docs/publish/start/
- HACS integration requirements: https://www.hacs.xyz/docs/publish/integration/
- HACS Action: https://www.hacs.xyz/docs/publish/action/

## Required Home Assistant Practices

- UI setup through Config Flow only.
- Runtime options through Options Flow.
- One planner instance only, declared through `single_config_entry`.
- Shared polling through `DataUpdateCoordinator`.
- First setup check through `async_config_entry_first_refresh`.
- Runtime data stored on `ConfigEntry.runtime_data`.
- Platforms forwarded through `async_forward_entry_setups`.
- Clean unload through `async_unload_entry`.
- Services registered in `async_setup` and errors raised when no loaded entry is available.
- Stable unique IDs, translated entity names and `_attr_has_entity_name = True`.
- Correct device classes, state classes and native units.
- Required-source failures mark dependent entities unavailable.
- Compact state attributes; large changing payloads stay in diagnostics, services or dedicated forecast sensors.
- No blocking I/O in the event loop.
- Planner logic remains independent from Home Assistant.

## Required HACS Practices

- Public GitHub repository.
- Useful GitHub description, topics and issues enabled.
- One integration under `custom_components/energy_planner`.
- Root `hacs.json` with honest minimum Home Assistant version.
- HACS-compatible `manifest.json` with required metadata.
- Brand assets under the integration `brand` directory.
- README covering install, configuration, entities, services, troubleshooting and migration.
- Full GitHub release for HACS releases; a tag alone is not enough.
- `main` remains stable and release-ready.

## Required Validation

Local:

```bash
uv run --extra ha --extra dev ruff check .
uv run --extra ha --extra dev ruff format --check .
uv run --extra ha --extra dev pytest -q
```

Remote:

- Ruff
- pytest
- Hassfest
- HACS Action for category `integration`

Real Home Assistant smoke test:

- install from the public HACS custom repository
- configure real HA source entities
- verify output sensors and service calls
- download diagnostics
- confirm there are no setup, entity or recorder warnings
