FROM oven/bun:1 AS web
WORKDIR /web
COPY web/package.json web/bun.lock ./
RUN bun install --frozen-lockfile
COPY web/ ./
RUN bun run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /bin/uv
RUN useradd --create-home --uid 1000 app && mkdir /app && chown app /app
USER app
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 PATH="/app/.venv/bin:$PATH"
COPY --chown=app pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY --chown=app api/ api/
COPY --from=web --chown=app /web/out web/out
# Trust X-Forwarded-For only from loopback and private Docker/LAN ranges (Traefik/Coolify), never "*", so clients cannot spoof their IP.
ENV FORWARDED_ALLOW_IPS="127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
EXPOSE 8765
# Keys come from the environment (docker run --env-file .env); the Qloo cache lives in /app/.cache/qloo.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8765", "--proxy-headers"]
