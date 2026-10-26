# Android / GrapheneOS — install and use

**Status:** companion **foundation shipped** (sideload debug APK + privacy / credential-export review). Not an F-Droid or Play Store release. Desktop PyQt6 remains the production client ([desktop.md](desktop.md)).

Privacy / credential model: [privacy-companion.md](privacy-companion.md). Cross-device trust: [cross-platform.md](cross-platform.md).

## What works today

1. **Native Kotlin companion** under [`companions/android/`](../companions/android/) — glance UI for `GET /api/v1/health|connections|backups` with Bearer auth (EncryptedSharedPreferences for the token). No Google Play Services.
2. **Pairing + export on the desktop** — SecureStore-backed pairing digest; sanitized connection export by default.
3. **Interim browser path** still valid — Vanadium → companion Web UI over an SSH/VPN tunnel.

## Desktop prerequisites

```bash
cd /path/to/DB_Storage_Manager
source .venv/bin/activate

# Option A: env token (gitignored)
./scripts/setup-api-token.sh

# Option B: SecureStore pairing (token shown once; only SHA-256 stored)
db-storage-manager-pair
# or: python -m db_storage_manager.security.pairing

# Optional sanitized inventory export (never dumps passwords without --i-consent)
db-storage-manager-export -o /tmp/dsm-export.json

./scripts/run-api-local.sh
```

Defaults: `http://127.0.0.1:8765/` — **localhost only**. Prefer an **SSH local forward** from the phone to that loopback rather than binding the API to the LAN.

```bash
curl -s http://127.0.0.1:8765/api/v1/health
curl -s -H "Authorization: Bearer $DSM_API_TOKEN" http://127.0.0.1:8765/api/v1/connections
```

Full API surface: [api.md](api.md), [cli.md](cli.md).

## Build and sideload the companion APK

Requirements: **JDK 17**, Android SDK (`platforms;android-35`), `ANDROID_HOME` writable.

```bash
cd companions/android
export JAVA_HOME=/path/to/jdk-17
export ANDROID_HOME=/path/to/Android/Sdk
./gradlew :app:assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Details: [`companions/android/README.md`](../companions/android/README.md).

On the phone:

1. Open **DSM Companion**.
2. Base URL: usually `http://127.0.0.1:8765` via your SSH forward (emulator: `http://10.0.2.2:8765`).
3. Paste the Bearer token from `db-storage-manager-pair` or `.env.api.local`.
4. **Save pairing**, then **Health** / **Connections** / **Backups**.

## Opsec (GrapheneOS)

| Topic | Guidance |
|---|---|
| Bind | Keep `DSM_API_HOST=127.0.0.1`. Do **not** bind `0.0.0.0` on an untrusted LAN. |
| Reachability | Prefer SSH/VPN tunnel from the phone to the host. |
| Token | Pairing Bearer or `DSM_API_TOKEN`. Phone stores token in EncryptedSharedPreferences only. |
| RBAC | When `users.enc` exists, unauthenticated API calls (except health/static) return **401**. Viewer Basic auth is fine for glance-only. |
| TLS | Companion is **plain HTTP** today — localhost/trusted-tunnel only. |
| Secrets | Never paste `.master-key`, connection passwords, or `--include-secrets` exports onto the phone. |
| GrapheneOS | Network permission discipline; prefer Vanadium for the browser interim path; sideload only APKs you built. |
| Scope | Glance / inventory / backup list — not a full DBA console. |

## Manual steps remaining

- F-Droid / signed release metadata (not prepared in this phase)
- TLS termination for non-tunnel use
- Optional Quest companion (see [quest.md](quest.md)) after UX research
