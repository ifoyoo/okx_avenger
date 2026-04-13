#!/usr/bin/env bash
set -euo pipefail

REMOTE_BRANCH="${REMOTE_BRANCH:-main}"
SERVICE_NAME="${SERVICE_NAME:-okx-avenger.service}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "${PROJECT_DIR}"

if [[ ! -d .git ]]; then
  echo "Project directory is not a git repository: ${PROJECT_DIR}" >&2
  exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Refusing to update with local tracked changes on the VPS checkout." >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "Missing .env in ${PROJECT_DIR}" >&2
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi

git fetch origin "${REMOTE_BRANCH}"
if git show-ref --verify --quiet "refs/heads/${REMOTE_BRANCH}"; then
  git checkout "${REMOTE_BRANCH}"
else
  git checkout -B "${REMOTE_BRANCH}" "origin/${REMOTE_BRANCH}"
fi
git pull --ff-only origin "${REMOTE_BRANCH}"

./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt -c constraints.txt

chmod 600 .env || true
if [[ -f watchlist.json ]]; then
  chmod 600 watchlist.json || true
fi
mkdir -p logs data

./.venv/bin/python cli.py config-check

if [[ "$(id -u)" -eq 0 ]]; then
  SYSTEMCTL=(systemctl)
else
  SYSTEMCTL=(sudo systemctl)
fi

"${SYSTEMCTL[@]}" daemon-reload
"${SYSTEMCTL[@]}" restart "${SERVICE_NAME}"
"${SYSTEMCTL[@]}" is-active "${SERVICE_NAME}"
"${SYSTEMCTL[@]}" status "${SERVICE_NAME}" --no-pager -l | sed -n '1,80p'
