#!/usr/bin/env bash
# Generate or refresh .env.api.local with a real DSM_API_TOKEN (gitignored).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT}/.env.api.local"
TOKEN="$(openssl rand -hex 32)"
umask 077
cat > "${ENV_FILE}" <<INNER
# Local REST companion secrets — gitignored (.env.*.local). Do not commit.
DSM_API_HOST=127.0.0.1
DSM_API_PORT=8765
DSM_API_TOKEN=${TOKEN}
INNER
chmod 600 "${ENV_FILE}"
echo "Wrote ${ENV_FILE} (mode 600). Token not printed."
echo "Run API: ${ROOT}/scripts/run-api-local.sh"
