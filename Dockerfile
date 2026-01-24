# syntax=docker/dockerfile:1

FROM oven/bun:1.3.6 AS frontend-build
WORKDIR /app/frontend

COPY frontend/package.json frontend/bun.lock ./
COPY frontend/tsconfig.json frontend/vite.config.ts frontend/index.html ./
COPY frontend/src ./src

RUN bun install --frozen-lockfile
RUN bun run build

FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY backend/pyproject.toml backend/README.md /app/backend/
COPY backend/app /app/backend/app
RUN pip install --no-cache-dir /app/backend

COPY --from=frontend-build /app/frontend/dist /app/frontend_dist
ENV FRONTEND_DIST_DIR=/app/frontend_dist

COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

EXPOSE 8000
CMD ["/app/start.sh"]
