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
- [ ] Rehearse full restore against live PostgreSQL and MySQL servers in CI (SQLite is covered today)

## Next

### Backups and recovery

- [ ] Google Drive as a plugin or an rclone `drive` remote (the library adapter stays out of the UI: a long-lived OAuth token in a desktop form is an opsec risk)
- [ ] Retention rules per connection (keep N daily / M monthly) with pruning for Local, Proton Drive and S3
- [ ] Restore into a scratch database for rehearsal before touching production
- [ ] Promote full restore from experimental to stable after the live-engine rehearsals above
- [~] Automatic restore on a critical alert — deferred. A restore replaces data, and an unattended trigger cannot tell a failing server from a failing probe. It would need opt-in per connection, a cooldown, a signed audit trail and a human confirmation path; manual experimental restore is the supported route until then

### Monitoring

- [ ] Anomaly alerts from a local sample history (growth, connections, cache hit ratio, slow queries)
- [ ] Additional alert channels (webhook, Slack) with the same cooldown and severity rules as email

### Plugin backlog: managed-database gaps

Planned on the existing `plugins.sdk` (API `1.0`): opt-in, real catalogs or provider APIs, no bundled credentials, and a clear "not available on this plan/role" instead of guessing.

- [ ] `pitr-verify` — confirm point-in-time recovery is enabled and the window matches retention (provider APIs, `pg_stat_archiver`)
- [ ] `schema-drift` — snapshot `information_schema` / `pg_catalog` and diff against a baseline or another connection
- [ ] `rls-audit` — Postgres tables exposed without row level security, permissive policies, `SECURITY DEFINER` functions
- [ ] `pooler-health` — compare direct and pooled endpoints (PgBouncer / Supavisor): latency, pool mode, `max_connections` headroom
- [ ] `encrypted-export` — per-table export (CSV / Parquet / SQL) in the DSMENC1 envelope with optional redaction
- [ ] `multi-cloud-discovery` — extend **Discover Cloud…** to DigitalOcean, Supabase, Neon, Aiven
- [ ] `extension-inventory` — installed vs available Postgres extensions and deprecations
- [ ] `trusted-sources-check` — firewall / allow-list settings versus the current public IP
- [ ] `maintenance-window-watch` — provider maintenance and version end-of-life in the alerts feed

Plugin acceptance bar: tests against a real SQLite/Postgres fixture or recorded provider responses, a manifest entry, a documented permission, and an RBAC permission (`plugins:manage` to install, `monitoring:*` / `backups:*` to run).

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
