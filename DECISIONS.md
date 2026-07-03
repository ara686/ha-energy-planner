# Architecture Decisions

## ADR-001: Planner-only v1

The integration will not control Victron, EV chargers or loads in v1.

Reason:
- safer rollout
- easier testing
- user automations remain in control

## ADR-002: Pure planner core

Planner logic must not depend on Home Assistant.

Reason:
- deterministic tests
- easier debugging
- possible reuse outside HA

## ADR-003: Internal history

The integration maintains its own history instead of depending on recorder internals.

Reason:
- stable behavior regardless of recorder purge settings
- simpler tests
- better portability

## ADR-004: Compact forecast attributes

The main forecast object should stay compact by default.

Reason:
- avoid huge HA states
- reduce recorder load

## ADR-005: Develop-based integration workflow

Development uses `develop` as the integration branch.

Feature and fix work is done on dedicated branches based on `develop`.
Branches are merged back into `develop` only after successful testing.
`main` stays stable and release-ready.

Reason:
- keep unfinished work out of the development integration branch
- make each change reviewable and testable before integration
- preserve a clean stable branch for releases

## ADR-006: HACS and Home Assistant quality gate

The integration targets HACS custom-repository compatibility from the start.

Implementation must follow current Home Assistant Developer documentation and
current HACS publishing requirements. Release candidates must pass local tests,
linting, Hassfest and HACS validation before being merged from `develop` to
`main` or published as a GitHub release.

Reason:
- avoid custom-integration patterns that Home Assistant is actively deprecating
- keep the repository installable and updatable through HACS
- make release readiness explicit instead of relying on manual inspection
