# GridWise LLM Energy Optimizer: Project Overview

## Purpose

The service solves the BUP CSE Fest 2026 GridWise preliminary task as one verifiable pipeline:

```text
request -> LLM interpretation -> guardrails -> LP optimizer -> replay -> response
```

The Problem Statement is canonical for directives, schemas, battery behavior, and plan validity. The Participant Guide defines scoring, reliability, deployment, and documentation requirements.

## Canonical Rules

- Each request contains exactly 24 unique hours and 1-3 operator notes.
- Each note maps to exactly one supported directive or `no_op`, in note order.
- Time windows are start-inclusive and end-exclusive: 1 PM to 3 PM is `[13, 14]`.
- A solar factor is the fraction remaining: 80% reduction is `0.20`; one quarter remaining is `0.25`.
- Relevant directives must be applied before optimization.
- Hourly plans must satisfy energy balance, solar availability, battery bounds and rates, directive constraints, nonnegative energy, and end-of-day battery neutrality.
- Reported totals are recalculated from the returned hourly plan.

## Module 1: API And Contract

Files: `app/main.py`, `app/schemas.py`, `app/errors.py`

- `GET /health` is provider-independent and returns `{"status":"ok"}`.
- `POST /optimize-energy` uses strict Pydantic request and response models.
- Unknown fields, non-finite values, incomplete hours, duplicate hours, blank notes, and invalid battery states are rejected.
- Malformed and structurally invalid requests return a stable HTTP 400 error envelope.
- Controlled provider, optimization, and replay failures do not expose secrets or stack traces.

## Module 2: LLM Interpreter

Files: `app/config.py`, `app/llm_interpreter.py`

- Uses the OpenAI Responses API with a discriminated Pydantic structured-output schema.
- Supports exactly `solar_reduction`, `minimum_battery_reserve`, `no_charge_window`, `no_discharge_window`, `max_grid_window`, and `no_op`.
- Injects battery capacity so percentage reserves can be converted to kWh.
- Checks interpretation count and `note_index` order before returning.
- Uses temperature 0 and does not store provider requests.
- The prompt states the canonical end-exclusive time convention and remaining-solar factor convention with worked examples.

## Module 3: Deterministic Guardrails

File: `app/guardrails.py`

The model output is treated as untrusted. Guardrails independently verify:

- note ordering and supported directive types;
- `applies` semantics;
- exact adjustment keys;
- unique, ascending hours in the range 0-23;
- finite solar, reserve, and grid-cap values;
- reserve values within battery capacity;
- nonnegative grid caps and factors in `[0, 1]`.

Validation is fail-closed. A malformed relevant directive is never silently converted into `no_op`; the service returns a controlled model-output error instead.

## Module 4: Optimizer And Replay

Files: `app/optimizer.py`, `app/replay.py`

The optimizer uses `scipy.optimize.linprog(method="highs")` with 96 decision variables:

- 24 grid-import variables;
- 24 battery-charge variables;
- 24 battery-discharge variables;
- 24 solar-use variables.

The objective minimizes total grid cost. Constraints encode hourly balance, battery bounds and rates, active reserve floors, charge/discharge outages, grid caps, solar limits, and end-of-day neutrality. Overlapping constraints use their most restrictive valid value. Solver charge/discharge values are netted before conversion to the single-action API schema.

The replay validator independently reconstructs every state transition and total. A plan is returned only after replay succeeds.

## Module 5: Service Pipeline

File: `app/service.py`

The service calls the modules in a fixed order:

1. Interpret every note.
2. Validate the full structured interpretation.
3. Solve the LP.
4. Replay the resulting plan against the same request and canonical directives.
5. Return replayed totals and a deterministic summary.

## Testing

The default suite is offline and deterministic:

```text
python -m pytest -q
```

Expected result: `185 passed, 1 skipped`.

Coverage includes API validation, all directive schemas, provider error mapping, prompt contract, fail-closed guardrails, LP constraints, replay failures, overlap behavior, simultaneous-flow serialization, all ten organizer plans, and optimizer reproduction of all ten organizer optimal costs.

The skipped test is the real-provider public interpretation check. Enable it with `RUN_LLM_INTEGRATION_TESTS=1` and a valid key.

## Public Samples

`tests/test_public_sample_totals_validator.py` performs two separate checks:

1. Replay the organizer's supplied plans and totals.
2. Run this project's optimizer using organizer interpretations and compare its recalculated cost with each organizer optimum.

The endpoint runner `scripts/run_public_sample.py` checks real LLM interpretation and plan totals against one or all public samples.

## Docker

Files: `Dockerfile`, `.dockerignore`, `docker-compose.yml`

- Python 3.11 slim base image.
- Runtime dependencies only.
- Non-root `gridwise` user.
- Port 8000 bound through Uvicorn on `0.0.0.0`.
- Internal `/health` probe.
- No `.env`, API key, tests, PDFs, or extraction artifacts in the image.

Build and health-check commands are documented in `README.md`. The exact public image tag/digest and live endpoint remain submission-time operational artifacts and must be recorded after publication.

## Scoring Rubric Mapping

| Category | Points | Evidence |
|---|---:|---|
| LLM Directive Interpretation | 25 | Structured schema, canonical prompt, ordered mapping, live public-sample test. |
| Directive Application And Constraint Correctness | 25 | LP constraints plus independent replay validation. |
| Optimization Quality | 10 | HiGHS cost minimization; all ten public optimum costs reproduced offline. |
| API Contract And Schema | 10 | Two endpoints, strict validation, ordered interpretation and 24-hour response. |
| Performance And Reliability | 10 | Provider-independent health, bounded timeout, controlled failures, deterministic LP. Full p95 must be measured on the submitted endpoint. |
| Deployment And Docker Fallback | 10 | Reproducible local image and health check. Live URL and pullable image reference must still be supplied. |
| Documentation And Local Reproducibility | 10 | Cross-platform quickstart, environment table, sample runner, expected results, architecture, dependencies, limitations, and secret guidance. |

## Submission Readiness Checklist

- [x] Canonical request and response schemas.
- [x] Required LLM interpretation path.
- [x] Deterministic guardrails, optimization, and replay.
- [x] Public sample fixtures and offline optimal-cost checks.
- [x] Cross-platform local quickstart.
- [x] Docker build/run instructions and internal health check.
- [ ] Run the live-model public-sample suite with the final provider key.
- [ ] Measure full endpoint p95 and valid-request failure rate.
- [ ] Publish and record an exact pullable image tag or digest.
- [ ] Deploy and record a stable externally reachable endpoint.
- [ ] Record and submit the required three-minute architecture video.

## Security And Limitations

- Secrets are read only from runtime environment variables and are excluded from Git and Docker context.
- Provider errors are sanitized before reaching clients.
- Model output is not trusted as executable instructions or optimization math.
- Battery efficiency is `1.0` because no efficiency fields exist in the challenge schema.
- Live LLM correctness and latency cannot be proven by offline tests; use the documented integration suite before submission.
