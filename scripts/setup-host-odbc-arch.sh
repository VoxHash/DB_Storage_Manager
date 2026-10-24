#!/usr/bin/env bash
# Host ODBC / optional-engine prerequisites for Arch Linux and derivatives
# (Garuda, Manjaro, EndeavourOS, …). Run from a terminal where `sudo` can
# prompt for your password.
#
# What this installs:
#   - unixODBC (driver manager) via pacman
#   - Microsoft ODBC Driver 18 for SQL Server via AUR package `msodbcsql`
#
# Oracle Instant Client is NOT installed here. python-oracledb Thin mode
# (default) needs no Instant Client for Oracle Database 12.1+. Use Thick mode
# only when required; see docs/installation.md and ORACLE_CLIENT_LIB_DIR.
#
# Usage:
#   chmod +x scripts/setup-host-odbc-arch.sh
#   ./scripts/setup-host-odbc-arch.sh
#   # then, in the project venv:
#   pip install -e ".[engines]"   # or ".[mssql]" / ".[oracle]"

set -euo pipefail

echo "==> Detecting package helpers"
if ! command -v pacman >/dev/null 2>&1; then
  echo "This script is for Arch-based systems (pacman not found)." >&2
  exit 1
fi

AUR_HELPER=""
for helper in paru yay; do
  if command -v "$helper" >/dev/null 2>&1; then
    AUR_HELPER="$helper"
    break
  fi
done
if [[ -z "$AUR_HELPER" ]]; then
  echo "Need an AUR helper (paru or yay) to install msodbcsql." >&2
  echo "Install paru, then re-run this script." >&2
  exit 1
fi

echo "==> Installing unixODBC (pacman)"
sudo pacman -S --needed --noconfirm unixodbc

echo "==> Installing Microsoft ODBC Driver 18 (AUR: msodbcsql)"
# Accepts Microsoft EULA via ACCEPT_EULA for non-interactive AUR builds when supported.
export ACCEPT_EULA=Y
"$AUR_HELPER" -S --needed --noconfirm msodbcsql

echo "==> Registered ODBC drivers:"
if odbcinst -q -d 2>/dev/null; then
  :
else
  echo "(odbcinst -q -d failed — check /etc/odbcinst.ini after install)" >&2
fi

echo
echo "Done. Next steps in the project venv:"
echo "  source .venv/bin/activate   # or: python3.12 -m venv .venv && source .venv/bin/activate"
echo "  pip install -e \".[engines]\""
echo "  python -c \"import pyodbc; print(pyodbc.drivers())\""
echo "  python -c \"import oracledb; print(oracledb.__version__, oracledb.is_thin_mode())\""
echo
echo "Oracle Thick mode (optional): install Instant Client manually, then:"
echo "  export ORACLE_CLIENT_LIB_DIR=/path/to/instantclient_XX_Y"
