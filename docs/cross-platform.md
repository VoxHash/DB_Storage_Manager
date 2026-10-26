# Cross-platform companions and shared trust

This guide is required because the product already ships a **local REST / Web companion**, shared **SecureStore** / backup directories, and optional **RBAC** that future Android / Quest surfaces are expected to reuse. Desktop remains the production client; phone and headset builds are exploratory.

## Surfaces

| Surface | Status | Role |
|---|---|---|
| Desktop PyQt6 (`db-storage-manager`) | **Production** | Full DBA workflow: connections, query, backups, monitoring, plugins, cloud discovery |
| REST + Web companion (`db-storage-manager-api`) | **Shipped** | Same-host glance UI + sanitized API over SecureStore / local backups |
| Android / GrapheneOS | **Future** | Planned companion; interim = hardened browser → API ([android-grapheneos.md](android-grapheneos.md)) |
| Meta Quest 3 class | **Future** | Planned spatial glance; interim = Quest Browser → API ([quest.md](quest.md)) |

## Shared data model

- Encrypted connection profiles, settings, SSH metadata, and RBAC accounts live under the desktop user-data directory (`~/.config/db-storage-manager/` on Linux/macOS; `%APPDATA%\DB Storage Manager\` on Windows).
- The companion process reads the **same** SecureStore and local backup directory when started on that host — it does not invent a separate cloud sync fabric.
- There is **no** first-party multi-device sync of `.master-key` or `*.enc` files. Copying those to phones or headsets is unsupported and unsafe by default.

## Auth across devices

1. **Bearer `DSM_API_TOKEN`** — system-admin style access for automation and interim browser clients. Store only in gitignored `.env.api.local` (mode `600`). Generate with `./scripts/setup-api-token.sh`.
2. **HTTP Basic** — when RBAC is active (`users.enc`), use a local username/password with the least role that fits (viewer vs user vs admin). Unauthenticated API calls (except health/static) return **401**; missing permissions return **403**.
3. **Desktop sign-in** — PyQt6 login dialog when RBAC accounts exist; independent of the Bearer token.

Do not reuse cloud IAM keys or Proton Drive passwords as API tokens.

## Networking and TLS

- Default bind: `127.0.0.1:8765` (localhost only) — correct for single-machine desktop + local browser.
- Interim phone/Quest access should prefer **SSH port forward** or VPN into that loopback, not open LAN exposure.
- If you must bind beyond localhost on an isolated lab network: set `DSM_API_HOST`, require `DSM_API_TOKEN`, enable RBAC, and treat traffic as **cleartext HTTP** until a documented TLS termination path exists.
- Never put the companion on the public internet without TLS, auth, and a threat model you accept.

## Backups and RBAC across devices

- Backup create/restore remains a **desktop** (or host-side) responsibility. Companion endpoints support list / verify / dry-run style operations — see [api.md](api.md).
- Proton Drive and S3 adapters run on the host that has rclone / cloud credentials; companions do not hold those secrets.
- Shared workstations: bootstrap RBAC once on the host; companions inherit enforcement when talking to that host’s API.

## Recommended interim topology

```
[Desktop host]
  db-storage-manager          ← primary UI
  db-storage-manager-api      ← 127.0.0.1:8765 + DSM_API_TOKEN (+ RBAC)
        ↑
        │ SSH / VPN tunnel (preferred)
        │
[GrapheneOS browser] / [Quest Browser]   ← glance only
```

## What this guide deliberately does not promise

- Native APK or Quest Store packages (not shipped)
- Encrypted multi-device sync of connection stores
- Full query console on phone or in VR

Track native companions under [ROADMAP.md](../ROADMAP.md) Future platforms. Desktop install: [desktop.md](desktop.md).
