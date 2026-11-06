#!/usr/bin/env bash
# devbox run smoke: run the smoke-tagged tests against a running deployment (platform-owned, spec 091).
# Prints `PASS|FAIL|SKIP  <path>::<name>` per test, then `smoke: <p> passed, <f> failed, <s> skipped`
# (or `0 smoke tests`). Exit 2 without SMOKE_BASE_URL, 1 when a test or the runner fails.
# SMOKE_READ_ONLY=1 (set by the platform outside dev, SMOKE_ENV names the environment) skips the tests
# marked `@pytest.mark.writes`, so only dev gets smoke data (#474).
set -uo pipefail

base="${SMOKE_BASE_URL:-}"
if [ -z "$base" ]; then
  echo "ERROR: SMOKE_BASE_URL is not set: devbox run smoke runs the smoke tests against a running deployment, e.g. SMOKE_BASE_URL=https://<host> devbox run smoke" >&2
  exit 2
fi
while [ "${base%/}" != "$base" ]; do base="${base%/}"; done
export SMOKE_BASE_URL="$base"
if [ "${SMOKE_READ_ONLY:-}" = "1" ]; then
  echo "read-only smoke${SMOKE_ENV:+ in $SMOKE_ENV}: tests marked @pytest.mark.writes are skipped" >&2
fi

out="$(mktemp)"
trap 'rm -f "$out"' EXIT

uv run python -m pytest tests/ -p scripts.smoke_pytest -m smoke --smoke-report --no-cov -p no:cacheprovider 2>&1 | tee "$out"
rc="${PIPESTATUS[0]}"

if ! grep -qE '^(smoke: [0-9]+ passed, [0-9]+ failed, [0-9]+ skipped|0 smoke tests|FAIL  \(smoke recipe\))$' "$out"; then
  echo "FAIL  (smoke recipe)"
  [ "$rc" -eq 0 ] && rc=1
fi
exit "$rc"
