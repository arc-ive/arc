# Multi-stage build: one dependency layer, two images.
#
#   base       third-party runtime dependencies (incl. the ~400 MB spaCy model)
#    ├── production   application only — no tests, no pytest, no Ruff
#    └── test         application + tests + test tooling
#
# Build explicitly by target:
#   docker build --target production -t arc:prod .
#   docker build --target test       -t arc:test .
#
# Or through compose: the `arc` service is production, `arc-test` is test.
#
# Why the split: before it, the single image installed ".[dev]" and COPYed
# tests/, so pytest, pytest-split, Ruff and the whole test corpus shipped to
# runtime. That is dead weight in the image and extra attack surface in a
# container that serves customer traffic. tests/ remains in the repository and
# in CI — it is only kept out of the production runtime.

# ---------------------------------------------------------------------------
# base — dependencies only
# ---------------------------------------------------------------------------
FROM python:3.14-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Third-party dependencies are installed from the manifest alone, before any
# application source is copied. This layer downloads the ~400 MB
# en_core_web_lg spaCy model (a direct-URL dependency in pyproject.toml), so
# it must be invalidated only by a dependency change and never by an ordinary
# code edit. A stub package satisfies setuptools' src-layout discovery so the
# install can resolve without the real sources; the stub is removed straight
# away and the real package is installed in the leaf stages.
#
# Note this installs "." and NOT ".[dev]": the dev extra belongs to the test
# stage alone, so the production image never resolves it.
COPY pyproject.toml .
RUN mkdir -p src/arc \
    && touch src/arc/__init__.py \
    && python -m pip install --upgrade pip \
    && python -m pip install . \
    && rm -rf src

# ---------------------------------------------------------------------------
# production — what actually serves traffic
# ---------------------------------------------------------------------------
FROM base AS production

# Everything below this line changes on an ordinary commit. Keeping it beneath
# the dependency layer is what makes the model download cacheable.
COPY src ./src
COPY scripts ./scripts
COPY .env.example ./

RUN python -m pip install --no-deps . \
    && chown -R 1000:1000 /app

ENV XDG_CACHE_HOME=/app/.cache
RUN mkdir -p /app/.cache && chown 1000:1000 /app/.cache

USER 1000:1000

EXPOSE 8000

CMD ["uvicorn", "arc.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---------------------------------------------------------------------------
# test — CI and local suite execution
# ---------------------------------------------------------------------------
FROM base AS test

# The dev extra is its own layer above the shared dependency layer, so adding
# or bumping a test tool re-resolves only this step and never re-downloads the
# spaCy model. The src stub is recreated because the base stage removed it and
# setuptools still needs a package to discover.
RUN mkdir -p src/arc \
    && touch src/arc/__init__.py \
    && python -m pip install ".[dev]" \
    && rm -rf src

COPY src ./src
COPY tests ./tests
COPY scripts ./scripts
COPY .env.example ./
# pytest-split reads this to balance the four CI groups by recorded duration.
# Absent, it falls back to splitting by test count: slower, never broken.
COPY .test_durations* ./

RUN python -m pip install --no-deps . \
    && chown -R 1000:1000 /app

ENV XDG_CACHE_HOME=/app/.cache
RUN mkdir -p /app/.cache && chown 1000:1000 /app/.cache

USER 1000:1000

EXPOSE 8000

CMD ["python", "-m", "pytest", "-q"]
