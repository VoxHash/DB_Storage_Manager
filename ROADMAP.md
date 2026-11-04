# Roadmap — DB Storage Manager

Status: **1.0.7** released (2026-11-03); the next release is collected under `[Unreleased]` in [CHANGELOG.md](CHANGELOG.md). Legend: `[x]` shipped, `[ ]` planned, `[~]` deliberately deferred.

## In progress (next release)

- [x] Single signed-in indicator (sidebar footer); redundant status bar removed
- [x] Tabbed Settings: General, Backups & Adapters, Notifications, Users & RBAC, Updates
- [x] Backup vs live size explained in the UI (stored file, dump size, live size at backup time)
- [x] Experimental full restore: off by default, `backups:restore`, typed confirmation, passphrase, safety backup, audit log
- [x] S3-compatible adapter at parity with Local and Proton Drive (encrypted, verified, dry-run, restore)
- [x] SMTP email alert channel, `monitor` role, watch-on-launch
- [x] Theme fixes (Light RBAC panel, scroll areas, plugin status colours)
- [x] Premium plugin licensing through LicenseChain (core and built-ins stay free; see "Plugin pricing and sustainability")
- [x] Liquid-glass tokens, icon-only buttons with accessible names, and a Reduce transparency switch
- [x] Rehearse full restore against live PostgreSQL and MySQL servers in CI (`tests/test_live_restore.py`, `.github/workflows/live-restore.yml`: PostgreSQL 14/15/16, MySQL 8.0; MariaDB 11 verified locally). Finding: restore replaces backed-up objects but keeps target-only ones, and PostgreSQL `--clean` fails loudly when a target-only table depends on a backed-up one — rehearse into a scratch database
- [x] Publish the first premium plugin: `pitr-verify` (`db_storage_manager/premium_plugins/pitr-verify`). LicenseChain products were already created (`PREMIUM_PRODUCT_IDS["pitr-verify"]`); `license.product_id` is the monthly product. Install needs `plugins:manage`; running it needs `monitoring:read`

## Next

### Backups and recovery

- [~] Google Drive as a plugin or an rclone `drive` remote. Deferred: a long-lived OAuth token in a desktop form is an opsec risk, and the library adapter stays out of the UI. Settings still lists it as API only
- [x] Retention rules per connection (keep N daily / M monthly) with pruning for Local, Proton Drive and S3. Off by default. Both counts at zero delete nothing. Google Drive is not pruned. Runs after a scheduled backup; `settings.retention.connections` overrides the default per connection id
- [x] Restore into a scratch database for rehearsal before touching production (Backups → Restore… → **Rehearse into a new scratch database**; type `SCRATCH`. Production is not written. SQLite writes a sibling `*.scratch-<stamp>.db`; PostgreSQL and MySQL `CREATE DATABASE dsm_scratch_…` on the same server)
- [ ] Promote full restore from experimental to stable after the live-engine rehearsals above pass in CI and the scratch-database restore exists (the dependent-table limitation above is the remaining blocker)
- [~] Automatic restore on a critical alert — deferred. A restore replaces data, and an unattended trigger cannot tell a failing server from a failing probe. It would need opt-in per connection, a cooldown, a signed audit trail and a human confirmation path; manual experimental restore is the supported route until then

### Monitoring

- [ ] Anomaly alerts from a local sample history (growth, connections, cache hit ratio, slow queries)
- [ ] Additional alert channels (webhook, Slack) with the same cooldown and severity rules as email
- [ ] **Email alerts as a plugin** (`connection-email-alerts`): per-connection SMTP, separate from the workstation-wide profile on Settings → Notifications. Each saved connection would have its own recipients, minimum severity and cooldown. The password stays in SecureStore (encrypted, same as today) and is not copied into the plugin directory or the audit log. The core channel already sends, so this is a credential-shaped migration rather than a small patch and is not built in this pass. Useful when two databases should page different people; not useful as a second global SMTP form
- [ ] **Multi-connection monitoring plugin** (`multi-connection-monitor`): one process watching several connections, for an on-call desk that today autostarts a single connection. Opsec: polls use credentials already in SecureStore (no new secret store), opt-in per connection, rate-limited, and it must not widen the `monitor` role into `query:*` or `backups:*`. A plugin that runs arbitrary SQL on every connection would be an unattended query runner. Deferred until anomaly alerts have a local sample history, so the plugin reads health checks rather than ad-hoc SQL. Not a quick win

### Plugin backlog: managed-database gaps

Planned on the existing `plugins.sdk` (API `1.0`): opt-in, real catalogs or provider APIs, no bundled credentials, and a clear "not available on this plan/role" instead of guessing.

- [x] `pitr-verify` — confirm point-in-time recovery is enabled and the window matches retention (provider APIs, `pg_stat_archiver`). Shipped as the first premium plugin
- [x] `schema-drift` — snapshot `information_schema` / `sqlite_master` and diff against a baseline or another connection. Shipped as the second premium plugin (`db_storage_manager/premium_plugins/schema-drift`); `license.product_id` is the monthly product on the current seller account
- [x] `rls-audit` — Postgres tables exposed without row level security, permissive policies, `SECURITY DEFINER` functions. Shipped (`db_storage_manager/premium_plugins/rls-audit`); `license.product_id` is the monthly product. SQLite and MySQL are `not_available` rather than a false all-clear. Install needs `plugins:manage`; running needs `monitoring:read`
- [x] `pooler-health` — compare direct and pooled endpoints (PgBouncer / Supavisor): latency, pool mode, `max_connections` headroom. Shipped (`premium_plugins/pooler-health`). The pooled connection is one the operator passes; a missing endpoint is `partial` and is not guessed. `SHOW pool_mode` failing is `not_available` for pool mode only. Running needs `monitoring:read`
- [x] `encrypted-export` — per-table export (CSV / Parquet / SQL) in the DSMENC1 envelope with optional redaction. Shipped (`premium_plugins/encrypted-export`). Parquet is `not_available` when this machine has no parquet engine. Plaintext is deleted after encryption. Running needs `backups:create`
- [ ] `multi-cloud-discovery` — extend **Discover Cloud…** to DigitalOcean, Supabase, Neon, Aiven
- [ ] `extension-inventory` — installed vs available Postgres extensions and deprecations
- [ ] `trusted-sources-check` — firewall / allow-list settings versus the current public IP
- [ ] `maintenance-window-watch` — provider maintenance and version end-of-life in the alerts feed

Plugin acceptance bar: tests against a real SQLite/Postgres fixture or recorded provider responses, a manifest entry, a documented permission, and an RBAC permission (`plugins:manage` to install, `monitoring:*` / `backups:*` to run).

### Plugin pricing and sustainability

The core app and the built-in `migration` and `data_comparison` plugins stay free. Only new, separately distributed premium plugins are gated, so maintenance and security work can be funded without turning the tool into a paywall. Prices are kept low enough to be reasonable worldwide, and anyone for whom they are still out of reach can write to contact@voxhash.dev for a discount; no one is asked to justify hardship in detail.

| | Monthly | Yearly | One-time (this major version) |
|---|---|---|---|
| One premium plugin | US$1.99 | US$16 | US$24 |
| All premium plugins (bundle) | US$4.99 | US$39 | US$59 |

- Buyers get every update (features, fixes, security, compatibility) while a subscription is active; a one-time licence keeps working and receives all updates for that major version. A new major version may need a new licence, announced in the changelog first
- LicenseChain holds the authoritative price and billing (one price and currency per product); `plugin.json` only mirrors it for display
- Optional donations without buying anything: https://github.com/sponsors/VoxHash (the same `github: voxhash` entry as `.github/FUNDING.yml`)
- Framework decision: stay on PyQt6. A Tauri, Electron or QML rewrite was evaluated against current desktop UI trends and is not justified; the liquid-glass look is delivered with Qt stylesheets, with accessibility (contrast, focus rings, Reduce transparency) taking priority over blur

### Agent / MCP control surface

- [~] Deferred. A model-facing surface would hold a path to credentials, backups and arbitrary SQL, so prompt injection becomes data exfiltration or destruction. Only as an opt-in thin layer after the plugin backlog, read-only first, no raw SQL, no credential access, per-session RBAC identity, per-call audit log, confirmation for writes, off by default

## Later

- [ ] Android / GrapheneOS companion: F-Droid metadata and signed release APK ([docs/android-grapheneos.md](docs/android-grapheneos.md))
- [ ] Meta Quest glance client, only after UX research shows value over a phone ([docs/quest.md](docs/quest.md))
- [ ] Optional TLS termination and richer alerts UI for companions

Out of scope for the near term: renaming the product or package, a mobile rewrite of the desktop UI, native Quest apps before UX research, running arbitrary SQL or full restore from companions. Opsec: [docs/cross-platform.md](docs/cross-platform.md), [docs/privacy-companion.md](docs/privacy-companion.md).

## Shipped

- [x] **1.0.7** — concurrent GUI job runner, system tray, Changelog & Updates dialog, adapter-aware verification, encrypted scheduler passphrase vault, RBAC `query:write` and login throttle, 11 complete locales, packaging fixes
- [x] Android / GrapheneOS companion foundation (pairing Bearer, sanitized export, sideload APK)
- [x] Per-tab content polish and glassmorphism scoped to panel roots
- [x] Platform guides and opsec ([docs/desktop.md](docs/desktop.md), [docs/cross-platform.md](docs/cross-platform.md))
- [x] Cloud-managed discovery (RDS / Cloud SQL / Azure SQL) with IAM / Entra tokens
- [x] Proton Drive backup adapter via rclone (DSMENC1 before upload)
- [x] Multi-user RBAC with encrypted `users.enc` and Settings admin UI
- [x] Plugin marketplace and public SDK (`plugins.sdk`, local registry)
- [x] REST companion and glance web UI (`db_storage_manager.api`)
- [x] Native zstd and optional AES-256-GCM backup encryption (Rust/PyO3 with Python fallbacks)
- [x] Backup verification: SHA-256 sidecars, dry-run restore
- [x] SQL engine connection pooling
- [x] Dashboard customization and saved layouts
- [x] Query Console optimization suggestions (heuristics plus live `EXPLAIN`)
- [x] Monitoring thresholds, channels and alert UX
- [x] SSH tunnel UX, hardened optional engine installs, expanded automated tests, native wheels in CI

Feedback and proposals: https://github.com/VoxHash/DB_Storage_Manager/issues · contact@voxhash.dev
