FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Third-party dependencies are installed from the manifest alone, before any
# application source is copied. This layer downloads the 400 MB
# en_core_web_lg spaCy model (a direct-URL dependency in pyproject.toml), so
# it must be invalidated only by a dependency change and never by an ordinary
# code edit. A stub package satisfies setuptools' src-layout discovery so the
# install can resolve without the real sources; the stub is removed straight
# away and the real package is installed below.
COPY pyproject.toml .
RUN mkdir -p src/arc \
    && touch src/arc/__init__.py \
    && python -m pip install --upgrade pip \
    && python -m pip install ".[dev]" \
    && rm -rf src

# Everything below this line changes on an ordinary commit. Keeping it beneath
# the dependency layer is what makes the model download cacheable.
COPY src ./src
COPY tests ./tests
COPY scripts ./scripts
COPY .env.example ./

RUN python -m pip install --no-deps . \
    && chown -R 1000:1000 /app

ENV XDG_CACHE_HOME=/app/.cache
RUN mkdir -p /app/.cache && chown 1000:1000 /app/.cache

USER 1000:1000

EXPOSE 8000

CMD ["uvicorn", "arc.main:app", "--host", "0.0.0.0", "--port", "8000"]
