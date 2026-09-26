#!/usr/bin/env bash
# Idempotent dependency setup for the BeneSense monorepo.
# Safe to run repeatedly and against cached state.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> Setting up backend (Python)"
# The Python venv/ensurepip module is required to create the virtualenv. The
# default base image usually ships it; install it if it is missing.
if ! python3 -c "import ensurepip" >/dev/null 2>&1; then
  echo "    python3-venv missing; installing via apt"
  sudo apt-get update -qq && sudo apt-get install -y -qq python3-venv
fi
python3 -m venv backend/.venv
# shellcheck disable=SC1091
source backend/.venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
deactivate

echo "==> Setting up frontend (Node)"
corepack enable
cd frontend
if [ -f pnpm-lock.yaml ]; then
  pnpm install --frozen-lockfile
else
  pnpm install
fi
cd "$REPO_ROOT"

echo "==> Install complete."
