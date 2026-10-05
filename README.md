# DB Storage Manager

[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.6+-blue.svg)](https://www.riverbankcomputing.com/software/pyqt/)
[![Release](https://img.shields.io/github/v/release/VoxHash/DB_Storage_Manager)](https://github.com/VoxHash/DB_Storage_Manager/releases)
[![CI](https://github.com/VoxHash/DB_Storage_Manager/actions/workflows/ci.yml/badge.svg)](https://github.com/VoxHash/DB_Storage_Manager/actions/workflows/ci.yml)

> Professional desktop application for visualizing and managing database storage, growth, and backups across multiple database engines. Built with Python and PyQt6 by VoxHash Technologies.

## Features

- **Multi-Database Support** — PostgreSQL, MySQL/MariaDB, SQLite, MongoDB, Redis; optional Oracle, SQL Server, ClickHouse, InfluxDB
- **Storage Analysis Dashboard** — Metrics, table/index sizing, growth-oriented views
- **Secure Connection Management** — Fernet-encrypted credential storage
- **Query Console** — Multi-engine queries with Safe Mode for write protection
- **Backup & Restore** — Local, S3, and Google Drive adapters with scheduling
- **Modern Desktop UI** — Cross-platform PyQt6 app with themes and i18n

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

Optional engines:

```bash
pip install -e ".[mssql,clickhouse,influxdb]"
pip install -e ".[oracle]"   # needs Oracle Instant Client
```

### Prerequisites

- Python 3.10–3.12 recommended
- Desktop session for the GUI (or `QT_QPA_PLATFORM=offscreen` for smoke tests)

## Usage

1. **Connections** — add/test/save encrypted profiles
2. **Dashboard** — analyze storage for a selected connection
3. **Query Console** — run queries; keep Safe Mode on for production
4. **Backups** — local/S3/Google Drive with optional schedules

Details: [docs/usage.md](docs/usage.md)

## Configuration

| Setting | Description | Default |
|---|---|---|
| Theme | `light`, `dark`, or `dracula` | `dark` |
| Language | i18n code | `en` |
| Safe Mode | Block non-SELECT queries | Enabled |
| Auto Connect | Connect on startup | Disabled |
| Notifications | Desktop notifications | Enabled |
| Telemetry | Anonymous telemetry | Disabled |

User data: `~/.config/db-storage-manager/` (Linux/macOS) or `%APPDATA%\DB Storage Manager\` (Windows).  
Reference: [docs/configuration.md](docs/configuration.md)

## Documentation

- [docs/index.md](docs/index.md) — documentation home
- [Getting Started](docs/getting-started.md)
- [Architecture](docs/architecture.md)
- [API](docs/api.md)
- [Troubleshooting](docs/troubleshooting.md)
- [FAQ](docs/faq.md)
- [Examples](docs/examples/example-01.md)

## Roadmap

See [ROADMAP.md](ROADMAP.md). Current focus: test coverage, optional-engine reliability, monitoring polish, and SSH tunnel UX.

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

MIT — see [LICENSE](LICENSE).

---

Maintained by VoxHash Technologies
