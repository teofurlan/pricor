# Stage 1: Build Web UI
FROM node:22-alpine AS web-builder
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Stage 2: Python environment
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PORT=8080 \
    PRICOR_MODEL_PROVIDER=gemini \
    PRICOR_GEMINI_MODEL=gemini-3.1-flash-lite

COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY --from=web-builder /app/src/pricor/web_dist ./src/pricor/web_dist

RUN uv pip install --system --no-cache "."

EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn pricor.entrypoints.wiring:app_from_env --factory --host 0.0.0.0 --port ${PORT:-8000}"]
