# Meta Quest (Quest 3 class) — install and use

**Status:** exploratory **Future platform** (see [ROADMAP.md](../ROADMAP.md)). There is **no** Quest Store app, sideload APK, or OpenXR / Unity build published today. Do not claim a native VR client exists yet.

The production client remains the **desktop** PyQt6 app ([desktop.md](desktop.md)).

## What works today (interim e2e)

Quest 3 class headsets include a browser. You can open the shipped **REST / Web companion** glance UI from that browser **only** when a trusted host runs `db-storage-manager-api` and you have a safe network path to it.

1. On the **desktop / lab host**:

   ```bash
   cd /path/to/DB_Storage_Manager
   source .venv/bin/activate
   ./scripts/setup-api-token.sh
   ./scripts/run-api-local.sh
   ```

2. Default bind is `127.0.0.1:8765` — the headset cannot reach localhost on another machine. Interim options:

   - SSH/VPN tunnel from a bridge device into the host’s loopback, **or**
   - Bind to a LAN address **only** on an isolated lab network with `DSM_API_TOKEN` required (see opsec)

3. On Quest Browser, open `http://<reachable-host>:8765/` and authenticate with Bearer token (or HTTP Basic when RBAC is active).

Companion details: [cli.md](cli.md), [api.md](api.md), [cross-platform.md](cross-platform.md).

## Intended future native install (not shipped)

Per ROADMAP:

- Spatial “ops glance” panel for lab operators — metrics and backup health in VR, **not** a primary DBA workstation
- Tentative approach: Unity or WebXR talking to the local companion service
- Quest Store packaging only after privacy review
- Out of scope initially: immersive query editing, full schema management, replacing the desktop app

Until that lands, the only honest Quest path is **browser → companion API**.

## Opsec (headset + companion)

| Topic | Guidance |
|---|---|
| Bind | Prefer `127.0.0.1` + tunnel. LAN bind (`0.0.0.0` / host IP) only on isolated lab Wi‑Fi you control. |
| Token | Always set `DSM_API_TOKEN`. Do not leave the companion open on shared guest Wi‑Fi. |
| RBAC | Enable local users on the host; use least-privilege roles from the headset browser. |
| TLS | Companion is plain HTTP today — acceptable only on localhost/trusted tunnel/isolated lab. No public exposure. |
| Secrets | Never enter Fernet master keys or DB passwords into Quest Browser storage / clipboard sync. |
| Scope | Glance / verify / dry-run only — run real DBA work on the desktop client. |

## Manual steps remaining

- Wait for a published WebXR / Unity / Quest Store companion (ROADMAP Future platforms), **or**
- Use Quest Browser against a hardened companion endpoint you operate
