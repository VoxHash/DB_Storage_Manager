# DB Storage Manager

[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.6+-blue.svg)](https://www.riverbankcomputing.com/software/pyqt/)

> Professional desktop application for visualizing and managing database storage, growth, and backups across multiple database engines. Built with Python and PyQt6 for cross-platform excellence.

## ✨ Features

- **Multi-Database Support** - PostgreSQL, MySQL/MariaDB, SQLite, MongoDB, Redis, Oracle, SQL Server, ClickHouse, InfluxDB
- **Storage Analysis Dashboard** - Comprehensive metrics, visualizations, and growth tracking
- **Secure Connection Management** - Encrypted credential storage with cryptography (Fernet)
- **Advanced Query Console** - Multi-database query execution with safe mode
- **Backup & Restore System** - Local, S3, and Google Drive backups with scheduling
- **Modern User Interface** - Cross-platform desktop app with theme support

## 🧭 Table of Contents

- [Quick Start](#-quick-start)
- [Installation](#-installation)
- [Usage](#-usage)
- [Configuration](#-configuration)
- [Architecture](#-architecture)
- [Roadmap](#-roadmap)
- [Contributing](#-contributing)
- [License](#-license)

## 🚀 Quick Start

```bash
# 1) Clone repository
git clone https://github.com/voxhash/db-storage-manager.git
cd db-storage-manager

# 2) Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3) Install dependencies
pip install -r requirements.txt

# 4) Run application
python -m db_storage_manager.main
```

## 💿 Installation

See [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) for platform-specific installation steps.

### Prerequisites

- Python 3.10 or higher
- pip or pipenv

### Installation Methods

**Using pip:**
```bash
pip install -r requirements.txt
```

**Using setup.py:**
```bash
pip install -e .
db-storage-manager
```

## 🛠 Usage

### Adding Database Connections

1. Open application and navigate to "Connections" tab
2. Click "Add Connection" button
3. Select database type and enter connection details
4. Click "Test Connection" to verify
5. Save connection (credentials are encrypted)

### Analyzing Storage

1. Select connection from Dashboard dropdown
2. Click "Analyze" to scan database storage
3. View detailed metrics, tables, and indexes
4. Export data as CSV (planned)

### Using Query Console

1. Navigate to "Query Console" tab
2. Select database connection
3. Write SQL/NoSQL queries
4. Toggle "Safe Mode" for write operations
5. Execute and view results

### Managing Backups

1. Go to "Backups" tab
2. Select connection and backup adapter (Local/S3/Google Drive)
3. Configure compression and encryption
4. Create backup or schedule automated backups

For detailed usage instructions, see [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md).

## ⚙️ Configuration

Access settings via **Settings** tab:

| Setting | Description | Default |
|---|---|---|
| Theme | Light, dark, or system theme | System |
| Language | Internationalization support | English |
| Safe Mode | Enable/disable write operations | Enabled |
| Auto Connect | Automatically connect on startup | Disabled |
| Notifications | System notification preferences | Enabled |

Full configuration reference: [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md#configuration)

## 🧩 Architecture

DB Storage Manager follows a modular architecture:

- **Database Layer**: Async database connections with unified interface
- **Security Layer**: Encrypted credential storage with cryptography (Fernet)
- **Backup System**: Pluggable backup adapters (Local, S3, Google Drive)
- **GUI Layer**: PyQt6-based desktop interface with theme support

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed technical architecture.

## 🗺 Roadmap

Planned milestones live in [ROADMAP.md](ROADMAP.md). For changes, see [CHANGELOG.md](CHANGELOG.md).

**Current Focus:**
- Enhanced database support (Oracle, SQL Server improvements)
- Real-time monitoring and alerts
- SSH tunneling for secure remote connections
- Plugin system architecture

## 🤝 Contributing

We welcome PRs! Please read [CONTRIBUTING.md](CONTRIBUTING.md) and follow the PR template.

**Quick Start for Contributors:**
```bash
git clone https://github.com/voxhash/db-storage-manager.git
cd db-storage-manager
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"
pytest
```

## 🔒 Security

Please report vulnerabilities via [SECURITY.md](SECURITY.md).

**Security Features:**
- Encrypted credential storage (cryptography/Fernet)
- Safe mode prevents dangerous operations
- Local-only operation (no external data transmission)
- Input validation and sanitization

See [docs/SECURITY.md](docs/SECURITY.md) for detailed security documentation.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 📚 Documentation

- **[Getting Started](docs/GETTING_STARTED.md)** - Setup and first steps
- **[Architecture](docs/ARCHITECTURE.md)** - Technical architecture details
- **[Security](docs/SECURITY.md)** - Security features and best practices
- **[Development Goals](DEVELOPMENT_GOALS.md)** - Short-term and long-term goals
- **[GitHub Topics](GITHUB_TOPICS.md)** - Recommended repository topics

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/voxhash/db-storage-manager/issues)
- **Discussions**: [GitHub Discussions](https://github.com/voxhash/db-storage-manager/discussions)
- **Contact**: See [SUPPORT.md](SUPPORT.md)

---

**Made with ❤️ by VoxHash**

*DB Storage Manager - Professional database management made simple!* 🗄️✨
