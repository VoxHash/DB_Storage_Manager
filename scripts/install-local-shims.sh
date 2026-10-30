#!/usr/bin/env bash
# Install ~/.local/bin shims that point ONLY at this repo's .venv entry points.
# On Linux, also install the application icon + .desktop launcher.
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

# Linux desktop icon + launcher (XDG)
if [[ "$(uname -s)" == "Linux" ]]; then
  ICONS_SRC="${ROOT}/db_storage_manager/resources/icons"
  HICOLOR="${HOME}/.local/share/icons/hicolor"
  APPS_DIR="${HOME}/.local/share/applications"
  mkdir -p "${APPS_DIR}"
  for size in 16 32 48 64 128 256; do
    dest="${HICOLOR}/${size}x${size}/apps"
    mkdir -p "${dest}"
    cp -f "${ICONS_SRC}/db-storage-manager-${size}.png" \
      "${dest}/db-storage-manager.png"
  done
  # Scalable SVG for HiDPI menus
  mkdir -p "${HICOLOR}/scalable/apps"
  cp -f "${ICONS_SRC}/db-storage-manager.svg" \
    "${HICOLOR}/scalable/apps/db-storage-manager.svg"

  DESKTOP_SRC="${ROOT}/packaging/linux/db-storage-manager.desktop"
  DESKTOP_DST="${APPS_DIR}/db-storage-manager.desktop"
  # Point Exec at the shim so PATH order does not matter
  sed "s|^Exec=.*|Exec=${BIN_DIR}/db-storage-manager|" \
    "${DESKTOP_SRC}" > "${DESKTOP_DST}"
  chmod 644 "${DESKTOP_DST}"
  echo "Installed ${DESKTOP_DST}"
  echo "Installed hicolor icons under ${HICOLOR}"
  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${APPS_DIR}" >/dev/null 2>&1 || true
  fi
  if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "${HICOLOR}" >/dev/null 2>&1 || true
  fi
fi

echo
echo "Ensure ${BIN_DIR} is on PATH. Verify:"
echo "  which -a db-storage-manager db-storage-manager-api"
