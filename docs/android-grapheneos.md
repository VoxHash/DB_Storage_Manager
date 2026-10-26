# Android / GrapheneOS — install and use

**Status:** exploratory **Future platform** (see [ROADMAP.md](../ROADMAP.md)). There is **no** native APK, F-Droid package, or Play Store build today. Do not expect a GrapheneOS-hardened companion APK yet.

The production client remains the **desktop** PyQt6 app ([desktop.md](desktop.md)).

## What works today (interim e2e)

Use the shipped **REST / Web companion** from a hardened browser on the phone, against a companion process that runs on a trusted desktop/lab host on the same trusted network (or over a VPN / SSH tunnel you control).

1. On the **desktop host**, install and run the companion (not on the phone):

   ```bash
   cd /path/to/DB_Storage_Manager
   source .venv/bin/activate
   ./scripts/setup-api-token.sh      # writes gitignored .env.api.local (mode 600)
   ./scripts/run-api-local.sh
   ```

2. Defaults: `http://127.0.0.1:8765/` — **localhost only**. A phone browser cannot reach that unless you deliberately change the bind and networking (see opsec below).

3. On GrapheneOS / Android, open the glance Web UI in a hardened browser (Vanadium or equivalent) **only** if you have a safe path to the companion (SSH local forward, WireGuard to the lab host, etc.).

4. Prefer interim reachability via **SSH port forward** from the phone (or a jump host) to `127.0.0.1:8765` on the desktop, rather than binding the API to the LAN.

Example desktop-side check:

```bash
curl -s http://127.0.0.1:8765/api/v1/health
curl -s -H "Authorization: Bearer $DSM_API_TOKEN" http://127.0.0.1:8765/api/v1/connections
```

Full API surface: [api.md](api.md), [cli.md](cli.md). Cross-device trust model: [cross-platform.md](cross-platform.md).

## Intended future native install (not shipped)

Per ROADMAP:

- Kotlin + Jetpack companion
- Optional F-Droid / sideload first; **no** Google Play Services hard dependency
- Goals: view encrypted connection **metadata**, backup status, local alerts — **not** a full on-device query console
- Credential model must **not** mirror Fernet master keys to mobile storage by default

Until that lands, treat any “install on Android” path as: **browser → companion API**, not a store APK.

## Opsec (GrapheneOS / phone browser)

| Topic | Guidance |
|---|---|
| Bind | Keep `DSM_API_HOST=127.0.0.1`. Do **not** bind `0.0.0.0` on an untrusted LAN. |
| Reachability | Prefer SSH/VPN tunnel from the phone to the host; avoid exposing HTTP on Wi‑Fi. |
| Token | Always set `DSM_API_TOKEN` (`.env.api.local`). Send `Authorization: Bearer …`. |
| RBAC | When `users.enc` exists, unauthenticated API calls (except health/static) return **401**. Use HTTP Basic with a least-privilege local user, or Bearer as system admin. |
| TLS | Companion is **plain HTTP** today. Treat it as localhost/trusted-tunnel only until TLS termination is documented and shipped. Do not put it on the public internet. |
| Secrets | Never paste `.master-key`, connection passwords, or cloud static keys into the phone. Do not sync `*.enc` stores to cloud photo/backup apps. |
| GrapheneOS | Use network permission discipline; prefer Vanadium; avoid installing unvetted companion APKs from random mirrors. |
| Scope | Companion endpoints are glance / verify / dry-run oriented — not a substitute for the desktop DBA workflow. |

## Manual steps remaining

- Wait for a published companion APK / F-Droid build (tracked under ROADMAP Future platforms), **or**
- Run desktop + companion and access via a hardened browser over a tunnel you control
