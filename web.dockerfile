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
RUN uv pip install --python /app/.venv/bin/python gunicorn


FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    ARROW_BACKEND_URL=http://backend:6001

WORKDIR /app

RUN groupadd --system arrow && useradd --system --gid arrow --home /app arrow

COPY --from=builder --chown=arrow:arrow /app/.venv /app/.venv
COPY --chown=arrow:arrow web ./web

USER arrow

EXPOSE 6002

CMD ["gunicorn", "--bind", "0.0.0.0:6002", "--workers", "2", "--access-logfile", "-", "web.app:app"]
