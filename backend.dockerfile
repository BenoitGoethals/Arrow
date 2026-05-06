# syntax=docker/dockerfile:1.7

FROM python:3.14-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY web ./web
COPY backend ./backend
COPY run.py ./

RUN uv sync --frozen --no-dev --no-editable


FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN groupadd --system arrow && useradd --system --gid arrow --home /app arrow \
    && mkdir -p /app/data && chown -R arrow:arrow /app

COPY --from=builder --chown=arrow:arrow /app/.venv /app/.venv
COPY --chown=arrow:arrow backend ./backend
COPY --chown=arrow:arrow config.xml ./config.xml

USER arrow

EXPOSE 6001

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "6001"]
