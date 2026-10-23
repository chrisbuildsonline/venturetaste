#!/usr/bin/env bash
# Clone the committed HEAD into a temp dir and follow the README like a new user.
# Fixture mode only, so no QLOO_API_KEY is needed. Any failing step stops the script.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dir="$(mktemp -d -t venturetaste-fresh-XXXXXX)"
echo "==> cloning $repo into $dir"
git clone --quiet "$repo" "$dir/venturetaste"
cd "$dir/venturetaste"

step() {
  echo
  echo "==> $*"
  "$@"
}

step bun run setup
echo
echo "==> (cd web && bunx playwright install chromium)"
(cd web && bunx playwright install chromium)

step bun run test
step bun run typecheck
step bun run e2e:ci

echo
echo "==> fresh clone OK: $dir/venturetaste"
