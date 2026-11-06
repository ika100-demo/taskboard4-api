#!/usr/bin/env bash
# Smoke start of the real image next to a throwaway Postgres (AC-002.13, AC-002.14).
# Needs the image taskboard4-api:scan (devbox run image-build) and a running Docker daemon.
set -euo pipefail

IMAGE="${IMAGE:-taskboard4-api:scan}"
PG_IMAGE="postgres:16-alpine"
SUFFIX="$(od -An -N6 -tx1 /dev/urandom | tr -d ' \n')"
NET="image-smoke-${SUFFIX}"
PG="image-smoke-pg-${SUFFIX}"
APP="image-smoke-app-${SUFFIX}"
STEP="start"

cleanup() {
  docker rm -f "$APP" "${APP}-nourl" "$PG" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT

fail() {
  echo "image-smoke: FAILED at step: ${STEP}" >&2
  docker logs "$APP" >&2 2>&1 || true
  exit 1
}
trap fail ERR

STEP="image present"
docker image inspect "$IMAGE" >/dev/null

STEP="create network"
docker network create "$NET" >/dev/null

STEP="start postgres"
PGPW="$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
docker run -d --name "$PG" --network "$NET" -e "POSTGRES_PASSWORD=${PGPW}" -e POSTGRES_USER=smoke \
  -e POSTGRES_DB=smoke "$PG_IMAGE" >/dev/null

STEP="wait for postgres"
for _ in $(seq 1 60); do
  if docker exec "$PG" pg_isready -U smoke -d smoke -h 127.0.0.1 >/dev/null 2>&1 \
    && docker exec "$PG" psql -U smoke -d smoke -h 127.0.0.1 -c 'SELECT 1' >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$PG" psql -U smoke -d smoke -h 127.0.0.1 -c 'SELECT 1' >/dev/null

STEP="start image"
DBURL="postgres://smoke:${PGPW}@${PG}:5432/smoke"
docker run -d --name "$APP" --network "$NET" --read-only --tmpfs /tmp --user 10001:10001 \
  -e "DATABASE_URL=${DBURL}" -p 127.0.0.1::8080 "$IMAGE" >/dev/null
PORT="$(docker port "$APP" 8080/tcp | head -n1 | sed 's/.*://')"
BASE="http://127.0.0.1:${PORT}"

STEP="wait for /health"
ok=0
for _ in $(seq 1 30); do
  if curl -fsS -m 2 "${BASE}/health" >/dev/null 2>&1; then ok=1; break; fi
  sleep 1
done
[ "$ok" = 1 ]

STEP="/health"
[ "$(curl -fsS -m 5 "${BASE}/health" | tr -d ' \n')" = '{"status":"ok"}' ]

STEP="/ready"
ok=0
for _ in $(seq 1 30); do
  if [ "$(curl -sS -m 5 "${BASE}/ready" | tr -d ' \n')" = '{"status":"ready"}' ]; then ok=1; break; fi
  sleep 1
done
[ "$ok" = 1 ]

STEP="POST /tasks"
TITLE="smoke-$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')"
CODE="$(curl -sS -m 10 -o /dev/null -w '%{http_code}' -X POST "${BASE}/tasks" \
  -H 'Content-Type: application/json' -d "{\"title\":\"${TITLE}\"}")"
[ "$CODE" = 201 ]

STEP="GET /tasks"
curl -fsS -m 10 "${BASE}/tasks" | grep -q "$TITLE"

STEP="start without DATABASE_URL"
NOURL="${APP}-nourl"
docker run -d --name "$NOURL" --read-only --tmpfs /tmp --user 10001:10001 "$IMAGE" >/dev/null
for _ in $(seq 1 30); do
  [ "$(docker inspect -f '{{.State.Running}}' "$NOURL")" = false ] && break
  sleep 1
done
RC="$(docker inspect -f '{{.State.ExitCode}}' "$NOURL")"
OUT="$(docker logs "$NOURL" 2>&1)"
docker rm -f "$NOURL" >/dev/null 2>&1 || true
if [ "$(echo "$OUT" | grep -c DATABASE_URL)" = 0 ] || [ "$RC" = 0 ]; then
  echo "exit code ${RC}: ${OUT}" >&2
  false
fi

trap - ERR
echo "image-smoke: ok"
