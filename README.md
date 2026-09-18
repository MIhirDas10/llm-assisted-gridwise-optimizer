# GridWise LLM Energy Optimizer

HTTP API for the BUP CSE Fest 2026 GridWise preliminary challenge. The service receives a 24-hour campus energy scenario, interprets 1-3 operator notes, applies deterministic guardrails, optimizes a battery/grid/solar schedule with a linear program, and replays every invariant from Section 09 before returning a machine-checkable JSON response.

All four modules of the planned pipeline are now implemented and tested:

1. **API + contract** — `GET /health`, `POST /optimize-energy`, strict request validation, response schema.
2. **LLM operator-note interpreter** — converts each operator note into one schema-constrained supported directive via OpenAI Structured Outputs.
3. **Deterministic guardrails** — re-validate the interpreter output as untrusted data and demote any malformed directive to a safe `no_op`.
4. **Optimizer + replay validator** — minimize grid cost with a 24-period LP, then re-derive every Section 09 invariant from the returned plan before responding.

## Architecture

```text
API input -> LLM interpreter -> apply_guardrails -> optimize_schedule -> replay_plan -> API response
```

`replay_plan` is the trust boundary before the response leaves the service: any violation raises `ReplayViolationError` and the request fails with HTTP 422 instead of returning a bad plan.

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
- `hourly_plan` (24 entries with `grid_kwh`, `solar_used_kwh`, `battery_action`, `battery_energy_after_kwh`)
- `total_grid_kwh`
- `total_cost_bdt`
- `peak_grid_kwh`
- `plan_summary`

Invalid requests return HTTP `422` with a stable error envelope. Guardrail violations, LP infeasibility, and replay violations each surface their own typed error code (`guardrail_violation`, `optimization_error`, `replay_violation`) so the client can distinguish structural problems from cost-engineering failures.

Unexpected downstream failures return a generic HTTP `500` response without exposing prompts, credentials, or stack traces to the caller.

LLM configuration, provider, invalid-output, and timeout failures return controlled `503`, `502`, or `504` responses respectively. `/health` never calls the model provider.

## Local Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Set `LLM_API_KEY` in `.env` before calling `/optimize-energy`.

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

The deterministic suite covers the API contract, all six directive schemas, provider request construction, battery context, malformed model output, note-index mismatches, timeouts, and controlled downstream failures. It mocks the provider and does not use an API key.

To evaluate the configured model against all official public directive interpretations:

```powershell
$env:RUN_LLM_INTEGRATION_TESTS="1"
pytest tests/test_public_sample_interpreter.py -q
```

This optional test makes real provider calls and may incur usage charges.

## Docker Fallback

The image is reproducible from the committed `Dockerfile` and is safe to submit as the container fallback. Build and run it locally with no secrets baked in:

```bash
docker build -t gridwise-optimizer:1.0.0 .
docker run --rm -p 8000:8000 -e LLM_API_KEY="$LLM_API_KEY" gridwise-optimizer:1.0.0
```

Or via docker-compose, which reads `LLM_API_KEY` from the host environment and refuses to start if it is missing:

```bash
docker compose up --build
```

Once the container is up:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

The image:

- Uses `python:3.11-slim` and a multi-stage-friendly single-stage layout.
- Installs runtime deps only (`requirements.txt`); dev/test extras are excluded by `.dockerignore`.
- Runs as a non-root user (`gridwise`).
- Exposes port `8000` and serves `/health`; the container HEALTHCHECK probes `/health` every 30s.
- Carries no API keys, model weights, or `.env` files — `LLM_API_KEY` is injected at runtime via `-e` or compose environment.
- Starts the API with `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 --proxy-headers`.

To push the fallback image during the judging window, retag for the registry the organizers accept (example: `ghcr.io/<org>/gridwise-optimizer:1.0.0`) and document the exact pull/run commands in your submission notes. The image should be reachable via that exact tag/digest and `/health` must return `{"status":"ok"}` without any code, prompt, or model changes.

## Environment Variables

Module 2 configuration is documented in `.env.example`:

- `LLM_PROVIDER`: currently `openai`
- `LLM_MODEL`: defaults to `gpt-4o-mini`
- `LLM_API_KEY`: required; `OPENAI_API_KEY` is also accepted
- `LLM_BASE_URL`: optional compatible endpoint override
- `LLM_TIMEOUT_SECONDS`: defaults to `20`
- `LLM_MAX_RETRIES`: defaults to `1`

Do not commit real secrets.

## LLM Role

The LLM participates directly in the `/optimize-energy` request path. The implementation uses the OpenAI Responses API with a strict Pydantic Structured Outputs schema, low-temperature extraction, one output per note, and explicit time-window and solar-factor semantics. Battery capacity is supplied so percentage-based reserve notes can be converted to kWh. Operator notes are treated as untrusted data inside the prompt.

Allowed directive types:

- `solar_reduction`
- `minimum_battery_reserve`
- `no_charge_window`
- `no_discharge_window`
- `max_grid_window`
- `no_op`

## LP Formulation

`app/optimizer.py` solves a single LP per request using `scipy.optimize.linprog` with the HiGHS solver. Variables, in order: `g[0..23]` (grid import), `c[0..23]` (battery charge), `d[0..23]` (battery discharge), `s[0..23]` (solar used, slack for greedy solar allocation) — 96 variables total.

- **Objective**: `minimize Σ_h g[h] · tariff[h]` (slacks have zero cost).
- **End-of-day neutrality**: `η_in · Σc − (1/η_out) · Σd = 0` (battery ends where it began).
- **Per-hour energy balance**: `g[h] + s[h] + d[h] = demand[h] + c[h]`.
- **Battery bounds**: `floor ≤ E_after[h] ≤ capacity` for every hour, where `E_after[h] = E₀ + η_in·Σ_{k≤h} c[k] − (1/η_out)·Σ_{k≤h} d[k]`.
- **Variable bounds**: `g[h]` capped by `max_grid_window` directives; `c[h]` zeroed inside `no_charge_window`; `d[h]` zeroed inside `no_discharge_window`; `s[h] ≤ effective_solar[h]`.

The current `Battery` schema does not expose charge/discharge efficiencies, so the optimizer assumes unit efficiency (`η_in = η_out = 1`). Hourly plan entries are rounded to 6 decimal places before the response is built.

## Replay Validator

`app/replay.py` re-derives every Section 09 invariant from the LP output and refuses to ship a plan that violates any of them. The validator checks: plan length is exactly 24; every `battery_action` is one of `charge`/`discharge`/`idle`; battery transitions obey `E_after = E_before ± magnitude`; per-hour `E_after` stays within `[active_floor, capacity]`; charge and discharge rates respect `max_charge_kwh_per_hour` / `max_discharge_kwh_per_hour`; `no_charge_window` and `no_discharge_window` directives forbid the corresponding action; `solar_used_kwh ≤ effective_solar[h]`; `max_grid_window` caps `grid_kwh`; energy balance closes (`grid + solar + discharge = demand + charge`); and the battery ends the day at its initial state.

## Known Limitations

- **Unit battery efficiency.** The `Battery` schema does not expose `charge_efficiency` / `discharge_efficiency` fields, so the optimizer assumes both are `1.0`. The LP is structured to accept those factors if the schema grows.
- **Live-model public-sample evaluation.** The optional integration test in `tests/test_public_sample_interpreter.py` is skipped unless `RUN_LLM_INTEGRATION_TESTS=1` and a real `LLM_API_KEY` is configured.
- **Docker registry push** is not performed automatically — `docker build` produces `gridwise-optimizer:1.0.0` locally. Push to your preferred registry (`docker tag` + `docker push`) before the judging window so the organizers can pull the fallback image by exact tag/digest.
