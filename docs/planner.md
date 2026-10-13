# Planner

Pure planner core. No Home Assistant imports allowed.

The planner receives normalized input models from the Home Assistant coordinator.
It must not read Home Assistant state directly and must not call Solcast or device APIs.

The planner must simulate battery SoC for at least 24 hours and for the configured
`forecast_horizon_hours` when that horizon is longer. PV input comes from Solcast
forecast data already collected by Home Assistant. Load input comes from the
integration history model built from Home Assistant energy entities.

Solcast `pv_estimate` values are normalized by the Home Assistant source parser
from kW to kWh using the forecast period length. The pure planner only receives
PV energy per period.

The default SoC sensor exposes the planned battery path, including grid-charge
planning and a time-varying low-tariff reserve. A separate passive forecast uses
only the configured physical minimum SoC. Both start from current battery SoC.

The low-tariff reserve protects only remaining high-tariff net demand until the
next sustained solar start, plus the configured minimum SoC and reserve margin.
A backwards pass computes this reserve for each slot in linear time. Elapsed
evening demand is no longer reserved during the following night, and subsequent
nights use their own solar and consumption forecasts. If no sustained solar
start exists, the reserve covers the remaining known forecast. The scalar
`lock_soc` reports the initial reserve, not a fixed floor for the whole horizon.
The managed forecast and incremental admission budget share the base-input
reserve schedule; adding a managed load cannot silently relax that schedule.
Explicit scalar locks remain supported by the pure forecast API for callers
that do not opt into `dynamic_nt_reserve`.

When `grid_charging_enabled` is false, the planner does not mark charging-window
slots, does not add simulated grid charge and keeps the `charge_now` decision
off. Low-tariff windows remain an independent input.

Each point contains:

- timestamp
- predicted SoC percent
- predicted battery kWh

The result must always include the +24 hour SoC point when enough input data is
available, even if the full forecast horizon is longer.

The planner also summarizes unused surplus by local calendar day and reports
time-slot and solar-input coverage separately. Tomorrow surplus is valid only
when both cover the entire next local day. The Home Assistant coordinator passes
that budget to the separate pure allocation module; device states and Home
Assistant entities never enter the planner core.

The pure managed-load allocation layer runs hot-water minimum, EV, generic and
hot-water flexible phases in that order. EV demand is normalized from
battery-side energy to charger input through charging efficiency, limited per
slot by maximum charging power and carried forward only while unmet. The
coordinator supplies fully normalized values. Today includes live EV and
hot-water demand plus each generic load's history-based daily estimate after
subtracting its measured consumption so far. A generic requested-energy entity
continues to describe tomorrow only. Tomorrow includes all types, while later
days repeat hot-water demand and carry EV remainder without repeating generic
demand.

Solar TUV and EV allocations require the configured per-source starting SoC
(default 50%) and sufficient instantaneous surplus. Battery state is kept at full
precision; rendered end-of-slot SoC never authorizes the slot's start. Accepted
solar thresholds are retained in the simulation, so inserting an earlier load
cannot invalidate a later session. Fixed heaters reserve their full input power;
EV input varies above the configured current/voltage/solar-phase minimum.
Short final requests shorten the timeline without weakening these power checks.
