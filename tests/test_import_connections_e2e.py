"""Optional live import probes — skip when paths missing or host unreachable."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from db_storage_manager.importers import (
    import_env_file,
    import_ssh_key_path,
    probe_connection_sync,
)

BRIGHTADS = Path("/run/media/raider/Gaming_Images/Clients/BrightAds/connections")
SSH_DIRS = [
    BRIGHTADS / "escortgirlsexy.com",
    BRIGHTADS / "transsexualdivas.com",
]
ENV_PATH = Path(
    "/run/media/raider/Gaming_Images/Clients/JosaCore/local/asesoresyasociados.org/.env"
)
TIMEOUT = float(os.environ.get("DSM_E2E_IMPORT_TIMEOUT", "25"))
RUN_LIVE = os.environ.get("DSM_E2E_IMPORT", "").strip() in {"1", "true", "yes"}


@pytest.mark.skipif(not RUN_LIVE, reason="Set DSM_E2E_IMPORT=1 to run live import probes")
@pytest.mark.parametrize(
    "directory",
    [p for p in SSH_DIRS if p.is_dir()],
    ids=[p.name for p in SSH_DIRS if p.is_dir()] or ["none"],
)
def test_live_ssh_import_probe(directory: Path):
    if not directory.is_dir():
        pytest.skip(f"missing {directory}")
    profile = import_ssh_key_path(directory)
    result = probe_connection_sync(profile, timeout=TIMEOUT)
    if not result.get("ok"):
        pytest.skip(f"probe failed (network/auth): {result.get('error')}")
    assert result["status"] == "pass"


@pytest.mark.skipif(not RUN_LIVE, reason="Set DSM_E2E_IMPORT=1 to run live import probes")
def test_live_env_import_probe():
    if not ENV_PATH.is_file():
        pytest.skip(f"missing {ENV_PATH}")
    profiles = import_env_file(ENV_PATH)
    assert profiles
    # Prefer pooler endpoint first if present (direct may be IP-allowlisted)
    ordered = sorted(
        profiles,
        key=lambda p: 0 if (p.get("extra") or {}).get("pgbouncer") else 1,
    )
    last_err = None
    for profile in ordered:
        result = probe_connection_sync(profile, timeout=TIMEOUT)
        if result.get("ok"):
            assert result["status"] == "pass"
            return
        last_err = result.get("error")
    pytest.skip(f"all env profiles failed probe: {last_err}")
