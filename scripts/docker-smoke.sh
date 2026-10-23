#!/usr/bin/env bash
# Build the image, run it with the real .env, and run the opt-in live Playwright spec against it.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
port=8799
name=venturetaste-smoke

docker build -t venturetaste .
docker rm -f "$name" >/dev/null 2>&1 || true
trap 'docker rm -f "$name" >/dev/null 2>&1 || true' EXIT
docker run -d --name "$name" --env-file .env -p "$port:8765" venturetaste

echo "==> waiting for /api/health"
for _ in $(seq 60); do
  curl -fs "http://127.0.0.1:$port/api/health" >/dev/null && break
  sleep 1
done
curl -fs "http://127.0.0.1:$port/api/health"
echo

cd web
BASE_URL="http://127.0.0.1:$port" bunx playwright test
