FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml .
COPY src ./src
COPY tests ./tests
COPY scripts ./scripts

RUN python -m pip install --upgrade pip \
    && python -m pip install ".[dev]" \
    && chown -R 1000:1000 /app

ENV XDG_CACHE_HOME=/app/.cache
RUN mkdir -p /app/.cache && chown 1000:1000 /app/.cache

USER 1000:1000

EXPOSE 8000

CMD ["uvicorn", "arc.main:app", "--host", "0.0.0.0", "--port", "8000"]
