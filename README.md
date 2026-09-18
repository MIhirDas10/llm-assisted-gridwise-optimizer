# GridWise LLM Energy Optimizer

FastAPI service for the BUP CSE Fest 2026 GridWise preliminary challenge. It converts 1-3 operator notes into the six supported structured directives, validates the model output, solves a 24-hour linear program, replays every scheduling invariant, and returns a machine-checkable response.

## Architecture

```text
POST /optimize-energy
  -> schema validation
  -> OpenAI structured-output interpreter
  -> deterministic fail-closed guardrails
  -> SciPy/HiGHS linear optimizer
  -> independent replay validator
  -> response
```

The language model is used only for note interpretation. Energy balance, battery transitions, directive enforcement, optimization, totals, and final validation are deterministic.

## Canonical Semantics

- Time windows are start-inclusive and end-exclusive. `1 PM to 3 PM` means hours `[13, 14]`.
- `solar_reduction.factor` is the usable fraction remaining. An 80% reduction means `0.20`; one quarter remaining means `0.25`.
- Every note produces exactly one interpretation in `note_index` order.
- Only `no_op` uses `applies=false` and `structured_adjustment=null`.
- Invalid model output fails with a controlled `502`; it is never silently changed into `no_op`.
- The returned plan must finish at the initial battery energy.

## Local Quickstart

Requirements: Python 3.11 or 3.12 and an OpenAI-compatible API key.

```text
git clone https://github.com/MIhirDas10/llm-assisted-gridwise-optimizer.git
cd llm-assisted-gridwise-optimizer
python -m venv .venv
```

PowerShell:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

POSIX shell:

```bash
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.example .env
```

Set `LLM_API_KEY` in `.env`, then start the service:

```text
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Check readiness:

```text
curl http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok"}
```

## Public Sample Check

With the API running and `LLM_API_KEY` configured:

```text
python scripts/run_public_sample.py --case SAMPLE-01
```

Expected output:

```text
SAMPLE-01: PASS, cost=38365.0, grid=2692.5, peak=175.0
```

Run all ten public cases with `--all`. This makes provider calls and may incur usage charges.

The offline public-fixture suite validates every organizer plan and independently confirms that this optimizer reaches every organizer optimal cost:

```text
python -m pytest tests/test_public_sample_totals_validator.py -q
```

Expected result: `60 passed`.

To check the configured model against all organizer interpretations:

```powershell
$env:RUN_LLM_INTEGRATION_TESTS="1"
python -m pytest tests/test_public_sample_interpreter.py -q
```

## Full Test Suite

```text
python -m pytest -q
```

Expected result without live-model tests: `185 passed, 1 skipped`.

## Configuration

| Variable | Default | Purpose |
|---|---:|---|
| `LLM_API_KEY` | required | Provider credential; never commit it. |
| `OPENAI_API_KEY` | unset | Accepted fallback credential name. |
| `LLM_PROVIDER` | `openai` | Supported provider mode. |
| `LLM_MODEL` | `gpt-4o-mini` | Model identifier. |
| `LLM_BASE_URL` | unset | Optional OpenAI-compatible base URL. |
| `LLM_TIMEOUT_SECONDS` | `8` | Timeout per provider attempt. |
| `LLM_MAX_RETRIES` | `1` | SDK retry count for transient failures. |

With the defaults, two provider attempts plus short retry backoff remain below the organizer's 30-second hard request timeout. Actual end-to-end p95 depends on the selected provider and deployment region and must be measured against the submitted endpoint.

## API Contract

- `GET /health` returns `200 {"status":"ok"}` without contacting the model provider.
- `POST /optimize-energy` accepts the canonical problem-statement request and returns `directive_interpretation`, `hourly_plan`, recalculated totals, and `plan_summary`.
- Malformed or structurally invalid requests return `400 request_validation_error`.
- Infeasible scenarios or failed replay return controlled `422` errors.
- Provider failures return controlled `502`, `503`, or `504` errors without prompts, credentials, or stack traces.

## Docker Fallback

Build and run locally:

```text
docker build --pull -t gridwise-optimizer:1.0.0 .
docker run --rm --name gridwise-optimizer -p 8000:8000 -e LLM_API_KEY="YOUR_KEY" gridwise-optimizer:1.0.0
curl http://127.0.0.1:8000/health
```

Or pull the published image from the GitHub Container Registry (built automatically
by [`.github/workflows/docker-publish.yml`](.github/workflows/docker-publish.yml)):

```text
docker pull ghcr.io/mihirdas10/llm-assisted-gridwise-optimizer:latest
docker run --rm -p 8000:8000 -e LLM_API_KEY="YOUR_KEY" ghcr.io/mihirdas10/llm-assisted-gridwise-optimizer:latest
curl http://127.0.0.1:8000/health
```

The image runs as the non-root `gridwise` user, binds to `0.0.0.0:8000`, and includes an internal `/health` check. Credentials are supplied only at runtime.

See [`DEPLOYMENT.md`](DEPLOYMENT.md) for the exact steps to publish the pullable image, deploy a live HTTPS endpoint (Render/Fly/any Docker host), and record the tag/digest and URL the submission requires. A local image name alone does not satisfy those organizer requirements.

## Dependencies And Credits

- FastAPI and Uvicorn: HTTP service.
- Pydantic: strict request, response, and structured-output schemas.
- OpenAI Python SDK: Responses API structured output.
- SciPy HiGHS: linear-programming optimizer.
- pytest and HTTPX: automated tests.

Versions are pinned in `requirements.txt` and `requirements-dev.txt`.

## Known Limitations

- Battery charge and discharge efficiency are fixed at `1.0` because the challenge schema has no efficiency fields.
- Live interpretation quality and end-to-end latency require a real provider key and network path; the default test run does not make paid calls.
- A stable external endpoint, public container reference, and three-minute submission video are operational submission artifacts and are not created by the source code alone.

See `PROJECT_OVERVIEW.md` for the module and rubric mapping.
