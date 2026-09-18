# GridWise LLM Energy Optimizer

HTTP API for the BUP CSE Fest 2026 GridWise preliminary challenge. The service receives a 24-hour campus energy scenario, interprets 1-3 operator notes, applies deterministic guardrails, optimizes a battery/grid/solar schedule, and returns a machine-checkable JSON response.

This repository is currently at **Module 1: API + Input/Output Contract**. It exposes the exact endpoints, strictly validates the request shape, normalizes valid hourly input into hour order, and returns controlled JSON errors. The returned optimization plan is a safe idle-battery placeholder until the LLM interpreter, guardrails, and optimizer modules are implemented.

## Architecture

The target challenge pipeline is:

```text
API input -> LLM interpreter -> guardrails/validator -> optimizer -> final API response
```

Planned modules:

1. **API + contract**: `GET /health`, `POST /optimize-energy`, strict request validation, response schema.
2. **LLM interpreter**: converts each operator note into one supported directive type.
3. **Guardrails**: treats LLM output as untrusted data and validates note order, directive type, hours, numeric ranges, and `no_op` semantics.
4. **Optimizer + replay validator**: applies directives, minimizes grid electricity cost, enforces energy balance, battery bounds/rates, grid caps, and end-of-day battery neutrality.

## Challenge Contract

### `GET /health`

Returns:

```json
{"status": "ok"}
```

### `POST /optimize-energy`

Accepts one JSON object with:

- `scenario_id`
- `operator_notes`: 1-3 non-empty strings
- `hours`: exactly 24 entries for hours `0` through `23`
- `battery`: capacity, initial energy, minimum energy, and charge/discharge limits

Successful responses include:

- `scenario_id`
- `directive_interpretation`
- `hourly_plan`
- `total_grid_kwh`
- `total_cost_bdt`
- `peak_grid_kwh`
- `plan_summary`

Invalid requests return HTTP `422` with a stable error envelope:

```json
{
  "error": {
    "code": "request_validation_error",
    "message": "The request body is invalid.",
    "details": []
  }
}
```

Unexpected downstream failures return a generic HTTP `500` response without exposing prompts, credentials, or stack traces to the caller.

## Local Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
```

Start the API:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Check readiness:

```bash
curl http://localhost:8000/health
```

Call the optimization endpoint:

```bash
curl -X POST http://localhost:8000/optimize-energy ^
  -H "Content-Type: application/json" ^
  -d "{\"scenario_id\":\"GRID-101\",\"operator_notes\":[\"The cafeteria menu changes tomorrow.\"],\"hours\":[{\"hour\":0,\"demand_kwh\":100,\"solar_kwh\":0,\"tariff_bdt_per_kwh\":6},{\"hour\":1,\"demand_kwh\":100,\"solar_kwh\":0,\"tariff_bdt_per_kwh\":6},{\"hour\":2,\"demand_kwh\":100,\"solar_kwh\":0,\"tariff_bdt_per_kwh\":6},{\"hour\":3,\"demand_kwh\":100,\"solar_kwh\":0,\"tariff_bdt_per_kwh\":6},{\"hour\":4,\"demand_kwh\":100,\"solar_kwh\":0,\"tariff_bdt_per_kwh\":6},{\"hour\":5,\"demand_kwh\":100,\"solar_kwh\":0,\"tariff_bdt_per_kwh\":6},{\"hour\":6,\"demand_kwh\":100,\"solar_kwh\":10,\"tariff_bdt_per_kwh\":8},{\"hour\":7,\"demand_kwh\":100,\"solar_kwh\":20,\"tariff_bdt_per_kwh\":10},{\"hour\":8,\"demand_kwh\":100,\"solar_kwh\":50,\"tariff_bdt_per_kwh\":12},{\"hour\":9,\"demand_kwh\":100,\"solar_kwh\":80,\"tariff_bdt_per_kwh\":14},{\"hour\":10,\"demand_kwh\":100,\"solar_kwh\":100,\"tariff_bdt_per_kwh\":16},{\"hour\":11,\"demand_kwh\":100,\"solar_kwh\":100,\"tariff_bdt_per_kwh\":16},{\"hour\":12,\"demand_kwh\":100,\"solar_kwh\":100,\"tariff_bdt_per_kwh\":15},{\"hour\":13,\"demand_kwh\":100,\"solar_kwh\":100,\"tariff_bdt_per_kwh\":14},{\"hour\":14,\"demand_kwh\":100,\"solar_kwh\":80,\"tariff_bdt_per_kwh\":13},{\"hour\":15,\"demand_kwh\":100,\"solar_kwh\":50,\"tariff_bdt_per_kwh\":14},{\"hour\":16,\"demand_kwh\":100,\"solar_kwh\":20,\"tariff_bdt_per_kwh\":18},{\"hour\":17,\"demand_kwh\":100,\"solar_kwh\":10,\"tariff_bdt_per_kwh\":22},{\"hour\":18,\"demand_kwh\":100,\"solar_kwh\":0,\"tariff_bdt_per_kwh\":28},{\"hour\":19,\"demand_kwh\":100,\"solar_kwh\":0,\"tariff_bdt_per_kwh\":30},{\"hour\":20,\"demand_kwh\":100,\"solar_kwh\":0,\"tariff_bdt_per_kwh\":26},{\"hour\":21,\"demand_kwh\":100,\"solar_kwh\":0,\"tariff_bdt_per_kwh\":18},{\"hour\":22,\"demand_kwh\":100,\"solar_kwh\":0,\"tariff_bdt_per_kwh\":10},{\"hour\":23,\"demand_kwh\":100,\"solar_kwh\":0,\"tariff_bdt_per_kwh\":7}],\"battery\":{\"capacity_kwh\":200,\"initial_energy_kwh\":80,\"minimum_energy_kwh\":30,\"max_charge_kwh_per_hour\":50,\"max_discharge_kwh_per_hour\":50}}"
```

## Tests

```bash
pytest
```

The current tests cover the Module 1 contract: health response, optimization response shape, malformed JSON, missing/duplicate hours, non-finite numbers, input normalization, and controlled downstream failures.

## Environment Variables

Module 1 does not require environment variables. Module 2 will require LLM configuration, documented in `.env.example`:

- `LLM_PROVIDER`
- `LLM_MODEL`
- `LLM_API_KEY`

Do not commit real secrets.

## LLM Role

The challenge requires a language-capable generative model in the operator-note interpretation path. The LLM must produce structured directive candidates only; deterministic guardrails will validate them before any optimizer constraint is changed.

Allowed directive types:

- `solar_reduction`
- `minimum_battery_reserve`
- `no_charge_window`
- `no_discharge_window`
- `max_grid_window`
- `no_op`

## Optimizer Plan

The intended optimizer is a linear programming or dynamic programming scheduler over 24 hourly periods. Its objective is:

```text
minimize sum(grid_kwh[h] * tariff_bdt_per_kwh[h])
```

It must enforce:

- hourly demand balance
- effective solar limits after directives
- battery capacity, reserve, and hourly charge/discharge limits
- no-charge/no-discharge windows
- max-grid windows
- final battery energy equal to initial energy
- reported totals matching the returned hourly plan

## Known Limitations

- Module 1 currently marks every operator note as `no_op`; this is intentionally a placeholder and does not satisfy the final mandatory LLM interpretation requirement.
- The current hourly plan uses available solar first and keeps the battery idle. It is valid as a contract baseline but is not cost-optimized and does not apply operator directives.
- Docker packaging is not added yet.
