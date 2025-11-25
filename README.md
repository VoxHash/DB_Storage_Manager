# 🗄️ DB Storage Manager v1.0.0

> **DB Storage Manager** - A professional desktop application for visualizing and managing database storage, growth, and backups across multiple database engines. Built with Python and PyQt6 for cross-platform excellence.

[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](https://github.com/voxhash/db-storage-manager)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.6+-blue.svg)](https://www.riverbankcomputing.com/software/pyqt/)

## ✨ Features

### 🗄️ **Multi-Database Support**

- **PostgreSQL** - Full driver with pg_stat analysis and pg_dump/pg_restore
- **MySQL/MariaDB** - Complete INFORMATION_SCHEMA support with mysqldump
- **SQLite** - File-based operations with PRAGMA analysis
- **MongoDB** - Collection and document analysis with mongodump
- **Redis** - Key-value analysis and memory usage tracking

### 📊 **Storage Analysis Dashboard**

- **Comprehensive Metrics** - Per-database and per-table size analysis
- **Visual Charts** - Interactive charts and visualizations
- **Growth Trends** - Historical storage growth tracking
- **Index Analysis** - Index size and bloat estimation
- **Export Capabilities** - CSV data export

### 🔐 **Secure Connection Management**

- **Encrypted Storage** - All credentials encrypted using cryptography (Fernet)
- **SSH Tunneling** - Secure remote database access (planned)
- **Safe Mode** - Blocks dangerous operations by default
- **Connection Testing** - One-click connection validation

### 🖥️ **Advanced Query Console**

- **Multi-Database Support** - Execute queries across different database types
- **Safe Execution** - User-controlled write operations
- **Query Results** - Tabular result display
- **Explain Plans** - Query optimization analysis

### 💾 **Backup & Restore System**

- **Local Backups** - File-based backup with compression
- **S3 Integration** - Cloud backup with S3-compatible storage
- **Google Drive Integration** - Backup to Google Drive
- **Scheduled Backups** - Automated backup scheduling
- **Encrypted Storage** - Secure backup encryption
- **One-Click Restore** - Easy database restoration

### 🎨 **Modern User Interface**

- **Native Look** - PyQt6 provides native look and feel
- **Professional Design** - Clean, modern interface
- **Cross-Platform** - Windows, macOS, and Linux support
- **Theme Support** - Light, dark, and system themes


## 🚀 Quick Start

### Prerequisites

- Python 3.10 or higher
- pip or pipenv

### Installation

#### Method 1: Using pip (Recommended)

1. **Clone Repository**

   ```bash
   git clone https://github.com/voxhash/db-storage-manager.git
   cd db-storage-manager
   ```

2. **Install Dependencies**

   ```bash
   pip install -r requirements.txt
   ```

3. **Run Application**
   ```bash
   python -m db_storage_manager.main
   ```

#### Method 2: Using setup.py

1. **Install Package**

   ```bash
   pip install -e .
   ```

2. **Run Application**
   ```bash
   db-storage-manager
   ```

#### Method 3: Development Setup

1. **Create Virtual Environment**

   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install Dependencies**

   ```bash
   pip install -r requirements.txt
   ```

3. **Run Application**
   ```bash
   python -m db_storage_manager.main
   ```

## 🎯 Usage

### Adding Database Connections

1. **Open Application** - Launch DB Storage Manager
2. **Navigate to Connections** - Click "Connections" tab
3. **Add Connection** - Click "Add Connection" button
4. **Configure Settings** - Enter database details and credentials
5. **Test Connection** - Click "Test Connection" to verify connectivity
6. **Save Connection** - Encrypted credentials are stored securely

### Analyzing Storage

1. **Select Connection** - Choose from your saved connections in Dashboard
2. **Run Analysis** - Click "Analyze" to scan database storage
3. **View Results** - Explore detailed storage metrics and tables
4. **Export Data** - Save data for reporting (planned)

### Managing Backups

1. **Create Backup** - Select connection and backup settings
2. **Schedule Backups** - Set up automated backup schedules
3. **Monitor Backups** - View backup history and status
4. **Restore Data** - One-click restore with confirmation

### Using Query Console

1. **Open Console** - Navigate to Query Console tab
2. **Select Connection** - Choose database connection
3. **Write Queries** - Enter SQL/NoSQL queries
4. **Execute Safely** - Safe mode blocks dangerous operations
5. **View Results** - Analyze query results

## 🔧 Configuration

### Settings

Access via **Settings** tab:

- **Theme** - Light, dark, or system theme
- **Language** - Internationalization support
- **Safe Mode** - Enable/disable write operations
- **Notifications** - System notification preferences
- **Telemetry** - Anonymous usage statistics (disabled by default)

### Security

- **Encrypted Storage** - All credentials encrypted with cryptography (Fernet)
- **Local-Only** - No external data transmission
- **Safe Mode** - Prevents accidental data modification
- **SSH Tunneling** - Secure remote connections (planned)

## 📁 Supported Databases

### Relational Databases

- **PostgreSQL** 12+ - Full feature support
- **MySQL** 8+ - Complete compatibility
- **MariaDB** 10+ - MySQL-compatible features
- **SQLite** 3+ - File-based database support

### NoSQL Databases

- **MongoDB** 4+ - Document database analysis
- **Redis** 6+ - Key-value store management

## 🛠️ Development

### Project Structure

```
db_storage_manager/
├── db/                    # Database connection modules
│   ├── base.py           # Base connection interface
│   ├── factory.py        # Connection factory
│   ├── postgres.py       # PostgreSQL connection
│   ├── mysql.py          # MySQL connection
│   ├── sqlite.py         # SQLite connection
│   ├── mongo.py          # MongoDB connection
│   └── redis.py          # Redis connection
├── backups/              # Backup system
│   ├── base.py           # Base backup adapter
│   ├── manager.py        # Backup manager
│   ├── local.py          # Local backup adapter
│   ├── s3.py             # S3 backup adapter
│   ├── googledrive.py    # Google Drive adapter
│   └── scheduler.py      # Scheduled backup manager
├── security/             # Security modules
│   └── store.py          # Encrypted storage
├── gui/                  # PyQt6 GUI components
│   ├── main_window.py    # Main window
│   ├── dashboard.py      # Dashboard widget
│   ├── connections.py    # Connections widget
│   ├── query.py          # Query console widget
│   ├── backups.py        # Backups widget
│   └── settings.py       # Settings widget
├── config.py            # Configuration
└── main.py              # Application entry point
```

### Available Commands

```bash
# Development
python -m db_storage_manager.main    # Run application
python -m pytest                     # Run tests

# Code Quality
black .                              # Format code
flake8 .                            # Lint code
mypy .                              # Type checking
```

### Building from Source

1. **Clone Repository**

   ```bash
   git clone https://github.com/voxhash/db-storage-manager.git
   cd db-storage-manager
   ```

2. **Install Dependencies**

   ```bash
   pip install -r requirements.txt
   ```

3. **Run Application**
   ```bash
   python -m db_storage_manager.main
   ```

## 🔧 Troubleshooting

### Common Issues

**Application won't start:**

- Ensure Python 3.10+ is installed
- Run `pip install -r requirements.txt` to install dependencies
- Check system requirements

**Database connection fails:**

- Verify database credentials
- Check network connectivity
- Ensure database server is running

**Backup operations fail:**

- Check disk space availability
- Verify backup directory permissions
- Ensure database is accessible

**PyQt6 installation issues:**

- On Linux: `sudo apt-get install python3-pyqt6` or `sudo yum install python3-qt6`
- On macOS: `brew install pyqt6`
- On Windows: pip should work directly

**Performance issues:**

- Close unnecessary applications
- Check system memory usage
- Restart the application

### Getting Help

- **Issues**: [GitHub Issues](https://github.com/voxhash/db-storage-manager/issues)
- **Discussions**: [GitHub Discussions](https://github.com/voxhash/db-storage-manager/discussions)
- **Documentation**: [Project Documentation](docs/)

## 📋 Changelog

See [CHANGELOG.md](CHANGELOG.md) for detailed version history and upcoming features.

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

## 📚 Documentation

- **[Getting Started](docs/GETTING_STARTED.md)** - Setup and first steps
- **[Architecture](docs/ARCHITECTURE.md)** - Technical architecture details
- **[Security](docs/SECURITY.md)** - Security features and best practices
- **[Roadmap](docs/ROADMAP.md)** - Development roadmap and future plans

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🎉 Acknowledgments

- **PyQt6** - Cross-platform GUI framework
- **Python** - Programming language
- **Database Drivers** - psycopg2, pymysql, aiosqlite, pymongo, redis
- **Community** - Feedback and contributions

---

**Made with ❤️ by VoxHash**

_DB Storage Manager - Professional database management made simple!_ 🗄️✨
