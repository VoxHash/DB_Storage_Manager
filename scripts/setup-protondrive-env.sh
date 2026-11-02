#!/usr/bin/env bash
# Create or refresh gitignored .env.protondrive.local for Proton Drive backups.
# Interactive prompts when stdin is a TTY; otherwise prints non-interactive docs.
# Does not invent passwords. Never prints secret values.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXAMPLE="${ROOT}/.env.protondrive.local.example"
ENV_FILE="${ROOT}/.env.protondrive.local"
VENV_PY="${ROOT}/.venv/bin/python"
CONFIG_DIR="${HOME}/.config/db-storage-manager"
RCLONE_CONF="${HOME}/.config/rclone/rclone.conf"

if [[ ! -f "${EXAMPLE}" ]]; then
  echo "Missing ${EXAMPLE}" >&2
  exit 1
fi

umask 077

copy_example() {
  cp "${EXAMPLE}" "${ENV_FILE}"
  chmod 600 "${ENV_FILE}"
  echo "Wrote ${ENV_FILE} from example (mode 600)."
}

if [[ ! -f "${ENV_FILE}" ]]; then
  copy_example
else
  echo "Keeping existing ${ENV_FILE} (not overwritten)."
  chmod 600 "${ENV_FILE}" || true
fi

echo "Mode: $(stat -c '%a' "${ENV_FILE}" 2>/dev/null || stat -f '%Lp' "${ENV_FILE}")"

fill_interactive() {
  local user_val pass_val otp_val
  echo
  echo "Enter Proton Drive credentials (values are not echoed to the shell history beyond this session)."
  echo "Press Enter to keep an existing non-empty value in ${ENV_FILE}."
  read -r -p "DSM_PROTONDRIVE_USERNAME: " user_val || true
  read -r -s -p "DSM_PROTONDRIVE_PASSWORD: " pass_val || true
  echo
  read -r -s -p "DSM_PROTONDRIVE_OTP_SECRET (optional): " otp_val || true
  echo

  python3 - "${ENV_FILE}" "${user_val:-}" "${pass_val:-}" "${otp_val:-}" <<'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1])
user, password, otp = sys.argv[2], sys.argv[3], sys.argv[4]
text = path.read_text(encoding="utf-8")
lines = text.splitlines()
updates = {}
if user.strip():
    updates["DSM_PROTONDRIVE_USERNAME"] = user.strip()
if password.strip():
    updates["DSM_PROTONDRIVE_PASSWORD"] = password.strip()
if otp.strip():
    updates["DSM_PROTONDRIVE_OTP_SECRET"] = otp.strip()
if not updates:
    print("No values entered; file unchanged.")
    raise SystemExit(0)
out = []
seen = set()
for line in lines:
    if not line or line.lstrip().startswith("#") or "=" not in line:
        out.append(line)
        continue
    key, _, _ = line.partition("=")
    key = key.strip()
    if key in updates:
        out.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        out.append(line)
for key, val in updates.items():
    if key not in seen:
        out.append(f"{key}={val}")
path.write_text("\n".join(out) + "\n", encoding="utf-8")
path.chmod(0o600)
print(f"Updated keys (names only): {', '.join(sorted(updates))}")
PY
}

if [[ -t 0 ]]; then
  fill_interactive
else
  echo
  echo "Non-interactive (no TTY). Edit credentials manually:"
  echo "  \$EDITOR ${ENV_FILE}"
  echo "Or re-run in a terminal: ./scripts/setup-protondrive-env.sh"
  echo "Prefer in-app: Settings → Configure Proton Drive… (SecureStore encrypted)."
fi

echo
echo "=== Host readiness (names / paths only; no secrets) ==="
if [[ -x "${HOME}/.local/bin/rclone" ]]; then
  echo "rclone: present at ~/.local/bin/rclone"
elif command -v rclone >/dev/null 2>&1; then
  echo "rclone: present on PATH ($(command -v rclone))"
else
  echo "rclone: missing — install from https://rclone.org/install/"
fi

if [[ -f "${RCLONE_CONF}" ]]; then
  if grep -q '^\[protondrive\]' "${RCLONE_CONF}" 2>/dev/null; then
    echo "rclone.conf: [protondrive] section present"
  else
    echo "rclone.conf: present, no [protondrive] section"
  fi
else
  echo "rclone.conf: missing (username/password or SecureStore still OK)"
fi

# Key presence only
python3 - "${ENV_FILE}" <<'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8") if path.is_file() else ""
needed = ("DSM_PROTONDRIVE_USERNAME", "DSM_PROTONDRIVE_PASSWORD")
for key in needed:
    val = ""
    for line in text.splitlines():
        if line.startswith(key + "="):
            val = line.split("=", 1)[1].strip().strip("'\"")
    status = "SET" if val else "EMPTY"
    print(f"{key}: {status}")
PY

if [[ -x "${VENV_PY}" ]]; then
  echo
  echo "=== App configuration_status (no secret values) ==="
  (
    cd "${ROOT}"
    "${VENV_PY}" - <<'PY'
from db_storage_manager.backups.protondrive import (
    configuration_status,
    load_protondrive_dotenv,
)

loaded = load_protondrive_dotenv()
print(f"env file loaded: {loaded}")
status = configuration_status()
for key in (
    "configured",
    "rclone_found",
    "rclone_path",
    "has_credentials",
    "remote_in_rclone_config",
    "remote",
    "remote_path",
):
    print(f"  {key}: {status.get(key)}")
if not status.get("configured"):
    print(f"  error: {status.get('error')}")
PY
  )
else
  echo "No ${VENV_PY} — create venv and: pip install -e ."
fi

echo
echo "Optional: copy ${ENV_FILE} → ${CONFIG_DIR}/.env.protondrive.local"
echo "so desktop launches that use a different cwd still load credentials."
echo "Done. Never commit ${ENV_FILE}."
