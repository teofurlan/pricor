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

# Laya runs on the CPU: install the CPU build of torch first so the laya package does not pull
# the CUDA wheels from PyPI. Only the files inference reads are copied (see .gcloudignore).
RUN uv pip install --system --no-cache --index-url https://download.pytorch.org/whl/cpu "torch==2.14.1" \
    && uv pip install --system --no-cache "." "laya==0.4.6"
COPY models/laya-pricor/ ./models/laya-pricor/

ENV PRICOR_LAYA_DEVICE=cpu \
    PRICOR_PRELOAD_MODELS=1 \
    PRICOR_WORKSPACES_DIR=/tmp/pricor-workspaces \
    PRICOR_WORKSPACES_BUCKET=run-sources-pricor-us-central1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn pricor.entrypoints.wiring:app_from_env --factory --host 0.0.0.0 --port ${PORT:-8000}"]
