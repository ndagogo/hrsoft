#!/usr/bin/env bash
# Production deploy helper for Docker Compose.
# Usage (from project root):
#   cp .env.example .env   # then edit production values
#   ./scripts/deploy.sh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  echo "Missing .env — copy .env.example and fill production values first."
  exit 1
fi

# shellcheck disable=SC1091
set -a
source .env
set +a

if [[ "${DJANGO_DEBUG:-True}" == "True" || "${DJANGO_DEBUG:-true}" == "true" ]]; then
  echo "Refusing to deploy with DJANGO_DEBUG=True. Set DJANGO_DEBUG=False in .env."
  exit 1
fi

echo "Building and starting stack..."
docker compose pull
docker compose build --pull
docker compose up -d

echo "Waiting for health..."
for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${HTTP_PORT:-80}/healthz/" >/dev/null 2>&1; then
    echo "Deploy healthy."
    docker compose ps
    exit 0
  fi
  sleep 2
done

echo "Health check did not pass in time. Recent logs:"
docker compose logs --tail=80 web nginx
exit 1
