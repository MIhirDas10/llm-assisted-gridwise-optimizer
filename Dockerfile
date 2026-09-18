# syntax=docker/dockerfile:1.7
# GridWise LLM Energy Optimizer — Docker fallback image.
#
# Builds a slim production image that runs the FastAPI service with uvicorn
# on port 8000.  The image does NOT bake any secrets; LLM_API_KEY must be
# supplied at runtime via `docker run -e LLM_API_KEY=...` or a docker secret.

FROM python:3.11-slim AS base

# Disable .pyc generation, keep stdout/stderr unbuffered so logs surface
# immediately inside the container.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

# Install system deps needed by scipy/numpy wheels (libgomp) and curl for the
# /health probe inside the entrypoint.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first so dependency layers cache independently
# of source code edits.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Copy only the application source.  Tests, sample JSON, PDFs, and other dev
# artefacts are excluded by .dockerignore.
COPY app ./app

# Create a non-root user and hand /app over so the runtime cannot write to the
# install location.
RUN groupadd --system --gid 1001 gridwise \
    && useradd --system --uid 1001 --gid gridwise --create-home gridwise \
    && chown -R gridwise:gridwise /app
USER gridwise

EXPOSE 8000

# Sanity check at container start: wait for /health to become 200 before
# declaring the service ready.  `--workers 2` lets uvicorn handle bursts while
# keeping the LP solve wall-clock low.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 2 --proxy-headers"]
