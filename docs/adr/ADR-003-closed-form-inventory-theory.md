# ADR-003: Closed-Form Inventory Theory, Not a Forecasting Model

## Status
Accepted

## Context
The replenishment domain's core decision — when and how much to reorder
per SKU/location — is informed by classic inventory-theory formulas
(safety stock, reorder point, economic order quantity), all of which
take a demand *forecast* (mean and standard deviation) as an input
rather than producing one. The case study's name mentions "demand
forecasting" alongside replenishment, raising the question of whether
SupplyIQ should include an actual forecasting model (e.g. a time-series
model predicting future demand from historical sales).

## Decision
SupplyIQ's replenishment domain consumes a demand forecast
(`SKULocation.daily_demand_forecast`, `demand_std_dev`) as an **input**
to the optimization layer — it does not include a forecasting model
that produces those numbers from historical data.

Rationale:
- **Demand forecasting and inventory optimization are genuinely
  separable concerns**, and in most real organizations, separately
  owned ones: a demand-planning/forecasting team (or a dedicated
  forecasting service, possibly ML-based) produces forecasts; an
  inventory-optimization layer consumes them to make reorder decisions.
  Conflating the two into one service would mean SupplyIQ couldn't be
  adopted by an organization that already has its own forecasting
  pipeline and just wants the optimization layer — exactly the kind of
  forced coupling RecoIQ's ADR-005 argued against in a different
  context (vendoring vs. hard-dependency on a sibling system).
- The safety-stock/EOQ formulas themselves are well-established,
  closed-form inventory theory — verified independently against
  textbook reference values during development (a daily-demand-100,
  std-dev-15, lead-time-5-day, 95%-service-level example produced a
  safety stock of 55.34 and reorder point of 555.34, matching the
  manual calculation exactly; the EOQ formula was separately checked
  against its own textbook form). There's no judgment call to make
  about *whether* to trust this math the way there would be for a
  forecasting model's predictions.
- This keeps the case study's scope focused on the optimization/copilot
  architecture pattern (the actual subject of this portfolio entry)
  rather than expanding into demand-forecasting model selection (ARIMA?
  Prophet? a gradient-boosted model on engineered features?), which is
  its own substantial body of work and arguably closer to BioMedIQ's or
  InferenceIQ's territory (model selection/training) than to this case
  study's (operations-research optimization, with an LLM copilot layer).

## Consequences
- `daily_demand_forecast` and `demand_std_dev` are treated as already-
  validated, already-computed inputs — the domain model performs no
  sanity-checking of whether a forecast "looks reasonable" beyond basic
  Pydantic constraints (positive demand, non-negative std dev). A
  production deployment integrating a real forecasting pipeline
  upstream would be responsible for that pipeline's own validation.
- This is an explicit scope boundary worth stating plainly: SupplyIQ is
  an inventory/network/routing *optimizer* with a natural-language
  layer, not an end-to-end demand-forecasting platform. Anyone
  evaluating this case study against the literal phrase "demand
  forecasting" in its description should understand it refers to the
  forecast as a consumed input to safety-stock math, not a forecasting
  model this system trains or serves.
- If demand forecasting were added in a future iteration, the natural
  integration point is a new service that produces `SKULocation` forecast
  fields, upstream of `ReplenishmentSolver` — the solver's interface
  would not need to change.
