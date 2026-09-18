# Deployment Guide

This guide produces the two operational artifacts the scoring rubric requires for
the **Deployment & Docker Fallback** category:

1. A **pullable Docker image** that reaches `/health` with a documented command.
2. A **live, externally reachable endpoint** serving `POST /optimize-energy`.

Everything else (build reproducibility, clean startup, no manual code changes) is
already satisfied by the repository.

---

## 1. Publish the pullable image (GHCR, automatic)

The repository ships a GitHub Actions workflow at
[`.github/workflows/docker-publish.yml`](.github/workflows/docker-publish.yml)
that builds and pushes the image to the GitHub Container Registry on every push
to `main`. It uses the built-in `GITHUB_TOKEN`, so **no registry secrets are
required**.

Steps:

```bash
git add .
git commit -m "Add deployment pipeline"
git push origin main
```

Then, once the "Publish Docker image" workflow completes:

1. Open **GitHub → your profile/repo → Packages → `llm-assisted-gridwise-optimizer`**.
2. **Package settings → Change visibility → Public** (so judges can pull anonymously).

The image is now pullable and runnable exactly as the judge will test it:

```bash
docker pull ghcr.io/mihirdas10/llm-assisted-gridwise-optimizer:latest
docker run --rm -p 8000:8000 \
  -e LLM_API_KEY="YOUR_KEY" \
  ghcr.io/mihirdas10/llm-assisted-gridwise-optimizer:latest
curl http://127.0.0.1:8000/health          # -> {"status":"ok"}
```

Record the exact tag or digest in your submission, e.g.:

```bash
docker inspect --format='{{index .RepoDigests 0}}' \
  ghcr.io/mihirdas10/llm-assisted-gridwise-optimizer:latest
```

### Manual alternative (no CI)

If you prefer to push by hand:

```bash
echo "$GHCR_PAT" | docker login ghcr.io -u MIhirDas10 --password-stdin
docker build -t ghcr.io/mihirdas10/llm-assisted-gridwise-optimizer:1.0.0 .
docker push ghcr.io/mihirdas10/llm-assisted-gridwise-optimizer:1.0.0
```

(`GHCR_PAT` is a classic Personal Access Token with the `write:packages` scope.)

---

## 2. Deploy a live endpoint

### Option A — Render (Docker blueprint, easiest)

The repo ships [`render.yaml`](render.yaml).

1. Push the repo to GitHub (step 1).
2. **Render dashboard → New → Blueprint → select this repository.**
3. Paste the real `LLM_API_KEY` when prompted (stored as an encrypted env var).
4. Render builds the Dockerfile and returns a public HTTPS URL.

Verify:

```bash
curl https://<your-service>.onrender.com/health
```

> The free instance sleeps after inactivity and adds cold-start latency. Use the
> `starter` plan (already set in `render.yaml`) or ping `/health` periodically to
> keep p95 latency inside the judging limit.

### Option B — Run the published image on any VM

On any host with Docker and an open port:

```bash
docker run -d --restart unless-stopped -p 80:8000 \
  -e LLM_API_KEY="YOUR_KEY" \
  --name gridwise \
  ghcr.io/mihirdas10/llm-assisted-gridwise-optimizer:latest
```

Point a DNS name or use the host's public IP; the endpoint is then
`http://<host>/optimize-energy`.

### Option C — Fly.io

```bash
fly launch --dockerfile Dockerfile --no-deploy
fly secrets set LLM_API_KEY="YOUR_KEY"
fly deploy
```

Set the internal port to `8000` and the health check path to `/health`.

---

## 3. Verify the live endpoint end-to-end

With `LLM_API_KEY` configured on the deployment, run one public sample against the
live URL from your machine:

```bash
python scripts/run_public_sample.py --base-url https://<your-service> --case SAMPLE-01
```

Expected:

```text
SAMPLE-01: PASS, cost=38365.0, grid=2692.5, peak=175.0
```

---

## 4. Submission checklist

- [ ] `docker-publish` workflow is green and the GHCR package is **public**.
- [ ] `docker pull ...` + `docker run ...` + `curl /health` verified from a clean machine.
- [ ] Exact image tag/digest recorded in the submission.
- [ ] Live HTTPS endpoint reachable; `/health` returns `{"status":"ok"}`.
- [ ] `run_public_sample.py --all` passes against the live endpoint.
- [ ] p95 latency and valid-request failure rate measured against the live endpoint.
