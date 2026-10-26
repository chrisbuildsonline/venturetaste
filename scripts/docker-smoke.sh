#!/usr/bin/env bash
# Build the image, run it with the real .env, and run the opt-in live Playwright spec against it.
# Then run it again in fixture mode with no key and check a diligence run works.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
port=8799
name=venturetaste-smoke

# Public images only, so an empty docker config sidesteps the host's credsStore helper (docker-credential-desktop.exe on WSL).
DOCKER_CONFIG=$(mktemp -d)
export DOCKER_CONFIG
trap 'docker rm -f "$name" >/dev/null 2>&1 || true; rm -rf "$DOCKER_CONFIG"' EXIT

docker build -t venturetaste .
docker rm -f "$name" >/dev/null 2>&1 || true

wait_for_health() {
  echo "==> waiting for /api/health"
  for _ in $(seq 60); do
    curl -fs "http://127.0.0.1:$port/api/health" >/dev/null && break
    sleep 1
  done
  curl -fs "http://127.0.0.1:$port/api/health"
  echo
}

echo "==> fixture mode, no key"
docker run -d --name "$name" -e VENTURETASTE_FIXTURES=1 -p "$port:8765" venturetaste
wait_for_health
out=$(curl -s -w '\n%{http_code}' -X POST "http://127.0.0.1:$port/api/diligence" \
  -H 'Content-Type: application/json' -d '{"acquirer": "Nike", "target": "Adidas"}')
code=${out##*$'\n'}
body=${out%$'\n'*}
if [ "$code" != 200 ] || ! grep -q '"bci"' <<<"$body"; then
  echo "fixture mode: expected 200 with a bci field, got HTTP $code: ${body:0:300}" >&2
  exit 1
fi
echo "fixture mode: HTTP 200 with bci"
docker rm -f "$name" >/dev/null

echo "==> real key"
docker run -d --name "$name" --env-file .env -p "$port:8765" venturetaste
wait_for_health

cd web
BASE_URL="http://127.0.0.1:$port" bunx playwright test
