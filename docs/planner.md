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

The SoC forecast output is a compact passive time series. It starts from the
current battery SoC and applies the normalized consumption and PV forecast
without assuming Energy Planner automations have already charged the battery or
prevented discharge. Plan-specific target simulations are reported separately by
the `vt_grid_import_kwh_at_target` and `charged_kwh_total_at_target` outputs.

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
