#!/usr/bin/env bash
# Create or refresh gitignored .env.cloud.local wired to vendor default chains.
# Does not invent access keys. Prints readiness without secret values.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXAMPLE="${ROOT}/.env.cloud.local.example"
ENV_FILE="${ROOT}/.env.cloud.local"
VENV_PY="${ROOT}/.venv/bin/python"

if [[ ! -f "${EXAMPLE}" ]]; then
  echo "Missing ${EXAMPLE}" >&2
  exit 1
fi

umask 077
if [[ ! -f "${ENV_FILE}" ]]; then
  cat > "${ENV_FILE}" <<'INNER'
# Local cloud-managed DB config — gitignored (.env.*.local). Do not commit.
# Prefer vendor default credential chains over pasting long-lived keys here.
# Maintained by scripts/setup-cloud-env.sh
#
# Authenticate on this machine (then restart the desktop app / API):
#   aws configure                                          # or IAM role / SSO
#   gcloud auth application-default login                  # + set project
#   az login && az account set --subscription <id>         # Entra / CLI

# --- AWS RDS (default credential chain) ---
DSM_AWS_REGION=us-east-1
# DSM_AWS_PROFILE=default
# DSM_AWS_ACCESS_KEY_ID=
# DSM_AWS_SECRET_ACCESS_KEY=
# DSM_AWS_SESSION_TOKEN=
# DSM_AWS_RDS_SSL_CA=/path/to/global-bundle.pem

# --- GCP Cloud SQL (ADC) ---
# DSM_GCP_PROJECT_ID=my-gcp-project
# DSM_GCP_CREDENTIALS=

# --- Azure SQL (DefaultAzureCredential) ---
# DSM_AZURE_SUBSCRIPTION_ID=
# DSM_AZURE_TENANT_ID=
# DSM_AZURE_CLIENT_ID=
# DSM_AZURE_CLIENT_SECRET=
INNER
  echo "Wrote ${ENV_FILE} (default-chain template, no static keys)."
else
  echo "Keeping existing ${ENV_FILE} (not overwritten)."
fi
chmod 600 "${ENV_FILE}"
echo "Mode: $(stat -c '%a' "${ENV_FILE}" 2>/dev/null || stat -f '%Lp' "${ENV_FILE}")"

echo
echo "=== Host credential presence (names / paths only) ==="
if [[ -f "${HOME}/.aws/credentials" ]]; then
  echo "AWS credentials file: present"
else
  echo "AWS credentials file: missing — run: aws configure"
fi
if [[ -n "${AWS_ACCESS_KEY_ID:-}" ]] || [[ -n "${AWS_PROFILE:-}" ]]; then
  echo "AWS_* env: set (names only; values not shown)"
else
  echo "AWS_* env: unset"
fi
if [[ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" ]]; then
  echo "GOOGLE_APPLICATION_CREDENTIALS: set"
elif [[ -f "${HOME}/.config/gcloud/application_default_credentials.json" ]]; then
  echo "gcloud ADC file: present"
else
  echo "GCP ADC: missing — run: gcloud auth application-default login"
fi
if command -v az >/dev/null 2>&1; then
  if az account show >/dev/null 2>&1; then
    echo "Azure CLI: logged in (subscription details not printed)"
  else
    echo "Azure CLI: installed but not logged in — run: az login"
  fi
else
  echo "Azure CLI: not installed — install az, then: az login"
fi

echo
echo "=== Package discovery status (no live cloud APIs) ==="
if [[ -x "${VENV_PY}" ]]; then
  "${VENV_PY}" - <<'PY'
from db_storage_manager.cloud.credentials import configuration_status, load_cloud_dotenv
from db_storage_manager.cloud import manager as _mgr  # noqa: F401 — import path check

loaded = load_cloud_dotenv()
print(f"env file loaded: {loaded}")
status = configuration_status()
for provider, info in status.items():
    ready = info.get("ready")
    auth = info.get("auth") or ("credentials_path" if "credentials_path" in info else "")
    extras = []
    if info.get("region"):
        extras.append(f"region={info['region']}")
    if info.get("project_id"):
        extras.append(f"project_id=set")
    if info.get("subscription_id"):
        extras.append(f"subscription_id=set")
    if "credentials_path" in info:
        extras.append(f"adc_path={'yes' if info['credentials_path'] else 'no'}")
    if auth:
        extras.append(f"auth={auth}")
    print(f"  {provider}: ready={ready}" + (f" ({', '.join(extras)})" if extras else ""))
print()
print("Note: aws ready=True with auth=default_chain means region is set;")
print("live Discover Cloud still needs a working AWS login (aws configure / SSO / role).")
print("GCP needs DSM_GCP_PROJECT_ID + ADC; Azure needs DSM_AZURE_SUBSCRIPTION_ID + az login.")
PY
else
  echo "No ${VENV_PY} — create venv and: pip install -e \".[cloud]\""
fi

echo
echo "Optional live dry discovery (only when you have real creds):"
echo "  DSM_LIVE_CLOUD=1 ${VENV_PY:-python} -m pytest tests/test_cloud_managed.py -k live -v"
echo "Done. Never commit ${ENV_FILE}."
