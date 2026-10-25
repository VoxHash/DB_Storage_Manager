# DB Storage Manager Documentation

Professional desktop application for visualizing and managing database storage, growth, and backups across multiple engines. Built with Python and PyQt6 by VoxHash Technologies.

## Guides

| Document | Description |
|---|---|
| [Getting Started](getting-started.md) | Prerequisites, first launch, and first workflows |
| [Quick Start](quick-start.md) | Minimal path from clone to running app |
| [Installation](installation.md) | Platform install, optional engines, troubleshooting installs |
| [Configuration](configuration.md) | Settings, paths, and environment expectations |
| [Usage](usage.md) | Connections, analysis, query console, backups |
| [CLI](cli.md) | Desktop launcher + REST/Web companion entry points |
| [API](api.md) | Python package surfaces and local REST companion |
| [Architecture](architecture.md) | Module layout, security model, async design |
| [Troubleshooting](troubleshooting.md) | Common failures and fixes |
| [FAQ](faq.md) | Short answers to frequent questions |

## Examples

| Example | Description |
|---|---|
| [Example 01 — SQLite storage analysis](examples/example-01.md) | Local SQLite connect, query, and analyze |
| [Example 02 — Encrypted connection store](examples/example-02.md) | Save and load credentials with Fernet encryption |

## Release alignment

Package / docs target version **1.0.5** (`db_storage_manager.__version__`, `setup.py`, GitHub Release `v1.0.5`). Post-tag work on `main` (SSH tunnel UX, monitoring alerts UX, optional live connection probes) is tracked under **Unreleased** in [CHANGELOG.md](../CHANGELOG.md) until the next tag.

## Project links

- [README](../README.md)
- [CHANGELOG](../CHANGELOG.md)
- [ROADMAP](../ROADMAP.md)
- [SECURITY](../SECURITY.md)
- [SUPPORT](../SUPPORT.md)
- [Contributing](../CONTRIBUTING.md)

Contact: contact@voxhash.dev
