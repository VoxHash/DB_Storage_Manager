#!/usr/bin/env bash
# Install ~/.local/bin shims that point ONLY at this repo's .venv entry points.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${ROOT}/.venv"
BIN_DIR="${HOME}/.local/bin"
mkdir -p "${BIN_DIR}"

for name in db-storage-manager db-storage-manager-api; do
  target="${VENV}/bin/${name}"
  if [[ ! -x "${target}" ]]; then
    echo "Missing ${target}; run: ${VENV}/bin/pip install -e \".[engines]\"" >&2
    exit 1
  fi
  shim="${BIN_DIR}/${name}"
  cat > "${shim}" <<INNER
#!/usr/bin/env bash
exec "${target}" "\$@"
INNER
  chmod +x "${shim}"
  echo "Installed ${shim} -> ${target}"
done

echo
echo "Ensure ${BIN_DIR} is on PATH. Verify:"
echo "  which -a db-storage-manager db-storage-manager-api"
