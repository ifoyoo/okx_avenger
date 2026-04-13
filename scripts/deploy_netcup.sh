#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-netcup}"
REMOTE_DIR="${REMOTE_DIR:-/root/apps/okx_avenger}"
REMOTE_BRANCH="${REMOTE_BRANCH:-main}"
SERVICE_NAME="${SERVICE_NAME:-okx-avenger.service}"
SYNC_ENV=0
SYNC_WATCHLIST=0

usage() {
  cat <<'EOF'
Usage: ./scripts/deploy_netcup.sh [--sync-env] [--sync-watchlist] [--remote-host HOST] [--remote-dir DIR] [--remote-branch BRANCH] [--service-name NAME]

Push local HEAD to origin/main, optionally upload .env/watchlist.json, then trigger the remote VPS update script.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --sync-env)
      SYNC_ENV=1
      ;;
    --sync-watchlist)
      SYNC_WATCHLIST=1
      ;;
    --remote-host)
      REMOTE_HOST="${2:?missing host}"
      shift
      ;;
    --remote-dir)
      REMOTE_DIR="${2:?missing directory}"
      shift
      ;;
    --remote-branch)
      REMOTE_BRANCH="${2:?missing branch}"
      shift
      ;;
    --service-name)
      SERVICE_NAME="${2:?missing service name}"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Refusing to deploy with uncommitted tracked changes. Commit or stash first." >&2
  exit 1
fi

REMOTE_REPO_URL="$(git remote get-url origin)"
REMOTE_PARENT_DIR="$(dirname "${REMOTE_DIR}")"

if [[ "${SYNC_ENV}" == "1" && ! -f .env ]]; then
  echo ".env not found in ${ROOT_DIR}" >&2
  exit 1
fi
if [[ "${SYNC_WATCHLIST}" == "1" && ! -f watchlist.json ]]; then
  echo "watchlist.json not found in ${ROOT_DIR}" >&2
  exit 1
fi

echo "Pushing local HEAD to origin/${REMOTE_BRANCH}"
git push origin HEAD:${REMOTE_BRANCH}

echo "Ensuring remote repository exists at ${REMOTE_HOST}:${REMOTE_DIR}"
ssh "${REMOTE_HOST}" "mkdir -p '${REMOTE_PARENT_DIR}' && if [ ! -d '${REMOTE_DIR}/.git' ]; then git clone '${REMOTE_REPO_URL}' '${REMOTE_DIR}'; fi"

if [[ "${SYNC_ENV}" == "1" ]]; then
  echo "Uploading .env to ${REMOTE_HOST}:${REMOTE_DIR}/.env"
  scp .env "${REMOTE_HOST}:${REMOTE_DIR}/.env"
fi

if [[ "${SYNC_WATCHLIST}" == "1" ]]; then
  echo "Uploading watchlist.json to ${REMOTE_HOST}:${REMOTE_DIR}/watchlist.json"
  scp watchlist.json "${REMOTE_HOST}:${REMOTE_DIR}/watchlist.json"
fi

echo "Running remote update script on ${REMOTE_HOST}"
ssh "${REMOTE_HOST}" "cd '${REMOTE_DIR}' && REMOTE_BRANCH='${REMOTE_BRANCH}' SERVICE_NAME='${SERVICE_NAME}' bash './scripts/update_vps.sh'"
