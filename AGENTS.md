# AGENTS.md

## Role

You are working on a Home Assistant custom integration named `energy_planner`.

## Hard rules

- Follow official Home Assistant integration architecture.
- Treat the current official Home Assistant Developer documentation and HACS documentation as source of truth.
- Use Config Flow and Options Flow.
- Use DataUpdateCoordinator.
- Keep planner logic independent from Home Assistant.
- Write tests for every behavior.
- Do not control devices in v1.
- Do not use Node-RED code directly.
- Do not use recorder internals as required dependency.
- Keep entity names and code identifiers in English.
- Prefer small, typed, testable modules.
- Never block the event loop.
- Never commit `nodered_export.json`; it is a local legacy reference only.
- When using the Node-RED export, use only the active flow path and ignore backup, archive and disconnected variants.

## Home Assistant development rules

- Keep setup UI-based through config entries; do not add YAML setup in v1.
- Keep `manifest.json` accurate, including `domain`, `name`, `documentation`, `issue_tracker`, `codeowners`, `config_flow`, `iot_class`, `requirements` and `version`.
- If only one planner instance is supported, declare `single_config_entry` and test duplicate setup behavior.
- Use `ConfigEntry.data` for persistent setup data and `ConfigEntry.options` for runtime-tunable options.
- Store runtime-only objects in typed `ConfigEntry.runtime_data`, not in untyped global `hass.data` structures.
- Implement `async_setup_entry` and `async_unload_entry`; clean listeners, subscriptions and resources on unload.
- Forward platforms with awaited `hass.config_entries.async_forward_entry_setups`.
- Use `DataUpdateCoordinator` for shared polling, pass the `config_entry` to it and call `async_config_entry_first_refresh` during setup.
- Raise `ConfigEntryNotReady` for temporary setup failures; raise `ConfigEntryError` or `ConfigEntryAuthFailed` only when appropriate.
- Prevent duplicate setup of the same planner instance.
- Mark entities unavailable when their required source data is unavailable or invalid.
- Give every entity a stable `unique_id`, `_attr_has_entity_name = True`, translated names and appropriate `device_class`, `state_class`, entity category and native units where applicable.
- Keep state attributes compact and recorder-friendly; large debug payloads belong in diagnostics or export services, not regular entity state.
- Register services in `async_setup`; validate service input and raise `ServiceValidationError` or `HomeAssistantError` on failures.
- Test Config Flow, Options Flow, setup, unload, services, diagnostics, sensors and coordinator behavior with Home Assistant test helpers, not only pure unit tests.
- Do not do blocking disk, network or heavy CPU work in the event loop; use HA async helpers or executor jobs when work can block.
- Use repairs issues and diagnostics for persistent insufficient data or misconfiguration.
- Before release-oriented changes, re-check current Home Assistant stable and beta/pre-release compatibility guidance.

## HACS rules

- Keep the repository installable as a HACS integration custom repository.
- Keep the integration under `custom_components/energy_planner`.
- Keep `hacs.json` in the repository root with an honest minimum supported Home Assistant version.
- Keep `README.md` usable for installation, configuration, entities, services, troubleshooting and migration notes.
- Keep the GitHub repository public before publishing through HACS.
- Maintain a clear GitHub repository description and useful topics.
- Keep the integration manifest HACS-compatible with at least `domain`, `documentation`, `issue_tracker`, `codeowners`, `name` and `version`.
- Add and maintain brand assets before HACS publishing.
- Validate release candidates with pytest, Ruff, Hassfest and the HACS Action for category `integration`.
- Publish a full GitHub release for HACS releases; a tag alone is not enough.
- Keep `main` as the public stable release branch. HACS can validate pushed branches, but installs without releases use the default branch, so merge `develop` to `main` only for release-ready code.

## Development workflow

- `develop` is the development integration branch.
- Create a dedicated branch for each development task.
- Base development branches on `develop`.
- Merge development branches back into `develop` only after successful testing.
- Do not merge unfinished or untested work into `develop`.
- Keep `main` for stable release-ready code.
- Before merging or pushing release candidates, run the local quality gate in `TESTING.md` and verify the remote Validate workflow.

## Coding style

- Python 3.12+ compatible.
- Use dataclasses or typed models for planner inputs/outputs.
- Keep all HA-specific code in integration modules.
- Keep algorithmic code in `planner.py` and related pure modules.
- Add diagnostics and useful warning messages.
