#!/usr/bin/env bash
# Start db-storage-manager-api using project .venv and .env.api.local.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${ROOT}/.venv"
ENV_FILE="${ROOT}/.env.api.local"

if [[ ! -x "${VENV}/bin/db-storage-manager-api" ]]; then
  echo "Missing ${VENV}/bin/db-storage-manager-api" >&2
  echo "Create venv and install: python3.12 -m venv .venv && .venv/bin/pip install -e \".[engines]\"" >&2
  exit 1
fi

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
else
  echo "No ${ENV_FILE}; API will start without DSM_API_TOKEN." >&2
  echo "Generate one: ${ROOT}/scripts/setup-api-token.sh" >&2
fi

exec "${VENV}/bin/db-storage-manager-api" "$@"
