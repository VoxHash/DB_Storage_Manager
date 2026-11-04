# DB Storage Manager

[![License](https://img.shields.io/badge/license-GPLv3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.6+-blue.svg)](https://www.riverbankcomputing.com/software/pyqt/)
[![Release](https://img.shields.io/github/v/release/VoxHash/DB_Storage_Manager)](https://github.com/VoxHash/DB_Storage_Manager/releases)
[![CI](https://github.com/VoxHash/DB_Storage_Manager/actions/workflows/ci.yml/badge.svg)](https://github.com/VoxHash/DB_Storage_Manager/actions/workflows/ci.yml)
[![Native wheels](https://github.com/VoxHash/DB_Storage_Manager/actions/workflows/native-wheels.yml/badge.svg)](https://github.com/VoxHash/DB_Storage_Manager/actions/workflows/native-wheels.yml)

> Professional desktop application for visualizing and managing database storage, growth, and backups across multiple database engines. Built with Python and PyQt6 by VoxHash Technologies.

## Features

- **Multi-Database Support** — PostgreSQL, MySQL/MariaDB, SQLite, MongoDB, Redis; optional Oracle, SQL Server, ClickHouse, InfluxDB
- **Storage Analysis Dashboard** — Metrics, table/index sizing, growth-oriented views
- **Secure Connection Management** — Fernet-encrypted credential storage; optional **Discover Cloud** for AWS RDS / GCP Cloud SQL / Azure SQL (IAM / Entra helpers)
- **Multi-user / RBAC** — Optional local accounts (`users.enc`), roles, and permission checks for shared workstations
- **SSH tunneling** — Paramiko bastion local port-forward from the Connections UI
- **Monitoring & alerts** — Live health banner, threshold alerts, acknowledge/refresh; desktop, in-app and real SMTP email channels; dedicated `monitor` role; optional watch-on-launch
- **Plugin marketplace (local)** — SDK + local registry: enable/disable, install from path or zip/tar.gz URL. The core and built-in plugins are free; optional premium plugins are licensed through [LicenseChain](https://licensechain.app) from US$1.99/month (updates included) and you can support the project at [GitHub Sponsors](https://github.com/sponsors/VoxHash)
- **Query Console** — Multi-engine queries with Safe Mode for write protection
- **Backup & Restore** — Local, Proton Drive (rclone) and S3-compatible adapters with scheduling, SHA-256 verification, dry-run, and an opt-in experimental full restore (RBAC-gated, audited)
- **Modern Desktop UI** — Cross-platform PyQt6 app with themes and i18n
- **Optional Rust acceleration** — PyO3 helpers for backup gzip, SHA-256 verification, and parallel hashing (pure-Python fallback)

## Table of Contents

- [Quick Start](#quick-start)
- [Installation](#installation)
- [Usage](#usage)
- [Configuration](#configuration)
- [Documentation](#documentation)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [Security](#security)
- [License](#license)

## Quick Start

```bash
git clone https://github.com/VoxHash/DB_Storage_Manager.git
cd DB_Storage_Manager
python3.12 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
pip install -e .
python -m db_storage_manager.main
```

Full walkthrough: [docs/quick-start.md](docs/quick-start.md)

## Installation

See [docs/installation.md](docs/installation.md) for platform notes and optional engines.

```bash
pip install -r requirements.txt
pip install -e .
db-storage-manager
```

Not on PyPI or npm (no JavaScript companion). To install a tagged release without cloning: `pip install "db-storage-manager @ git+https://github.com/VoxHash/DB_Storage_Manager.git@v1.0.7"`. **Help → Changelog & Updates** checks GitHub Releases on demand (stable / experimental channel, no auto-install).

Optional engines:

```bash
pip install -e ".[mssql,clickhouse,influxdb]"
pip install -e ".[oracle]"    # oracledb Thin mode; Instant Client only for Thick mode
pip install -e ".[engines]"   # all optional Python drivers
pip install -e ".[cloud]"    # RDS / Cloud SQL / Azure SQL discovery SDKs
```

Optional native performance module (prebuilt wheels on GitHub Releases — no Rust required):

```bash
# Download the matching db_storage_native-*.whl from the latest release, then:
pip install ./db_storage_native-*.whl
python -c "from db_storage_manager.native import backend_info; print(backend_info())"
```

Developers building from source still need Rust + maturin (`pip install -e ".[native]"` then `maturin develop --release` under `native/db_storage_native`). See [docs/installation.md](docs/installation.md).

### Prerequisites

- Python 3.10–3.12 recommended
- Desktop session for the GUI (or `QT_QPA_PLATFORM=offscreen` for smoke tests)
- Optional: `db_storage_native` wheel from Releases, or Rust + maturin to build locally

## Usage

1. **Connections** — add/test/save encrypted profiles (optional SSH bastion tunnel)
2. **Dashboard** — analyze storage for a selected connection
3. **Query Console** — run queries; keep Safe Mode on for production
4. **Monitoring** — health metrics and acknowledgeable alerts
5. **Plugins** — local marketplace: enable/disable, install from path or URL
6. **Backups** — local / Proton Drive / S3 with optional schedules; hover the size cells to see how the stored file relates to the live database
7. **Settings** — tabs for General, Backups & Adapters, Notifications, Users & RBAC and Updates

Details: [docs/usage.md](docs/usage.md)

## Configuration

| Setting | Description | Default |
|---|---|---|
| Theme | `light`, `dark`, or `dracula` | `dark` |
| Language | i18n code | `en` |
| Safe Mode | Block non-SELECT queries | Enabled |
| Auto Connect | Connect on startup | Disabled |
| Notifications | Desktop notifications | Enabled |
| Notification auto-dismiss | Seconds before a notification closes (clamped 2–60) | `5` |
| Telemetry | Anonymous telemetry | Disabled |
| Experimental full restore | Settings → Backups & Adapters, or `DSM_EXPERIMENTAL=1` | Off |
| Email alerts | SMTP host / security / recipients / minimum severity / cooldown (Settings → Notifications) | Off |

User data: `~/.config/db-storage-manager/` (Linux/macOS) or `%APPDATA%\DB Storage Manager\` (Windows).  
Reference: [docs/configuration.md](docs/configuration.md)

## Documentation

- [docs/index.md](docs/index.md) — documentation home
- [Desktop install & use](docs/desktop.md) — production PyQt6 client (Linux / macOS / Windows)
- [Android / GrapheneOS](docs/android-grapheneos.md) — sideload Kotlin companion + pairing; browser interim still valid
- [Companion privacy](docs/privacy-companion.md) — credential export + pairing model
- [Meta Quest](docs/quest.md) — future companion; interim browser → API
- [Cross-platform companions](docs/cross-platform.md) — shared SecureStore / RBAC / API opsec
- [Getting Started](docs/getting-started.md)
- [Architecture](docs/architecture.md)
- [API](docs/api.md)
- [Troubleshooting](docs/troubleshooting.md)
- [FAQ](docs/faq.md)
- [Examples](docs/examples/example-01.md)

## Roadmap

See [ROADMAP.md](ROADMAP.md). Desktop remains primary; platform guides and cloud default-chain setup are tracked under Shipped / Next.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md). Use Conventional Commits and the PR template.

```bash
pip install -e ".[dev]"
pytest -v
```

## Security

Report vulnerabilities to contact@voxhash.dev — [SECURITY.md](SECURITY.md).

## Support

- Issues: https://github.com/VoxHash/DB_Storage_Manager/issues
- Contact: contact@voxhash.dev — [SUPPORT.md](SUPPORT.md)

## License

[GNU General Public License v3.0](LICENSE) (GPL-3.0-only).

---

Maintained by VoxHash Technologies
