# 🗄️ DB Storage Manager v1.0.0

> **DB Storage Manager** - A professional desktop application for visualizing and managing database storage, growth, and backups across multiple database engines. Built with Electron, React, and TypeScript for cross-platform excellence.

[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](https://github.com/voxhash/db-storage-manager)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Electron](https://img.shields.io/badge/electron-31+-blue.svg)](https://electronjs.org/)
[![React](https://img.shields.io/badge/react-18+-blue.svg)](https://reactjs.org/)
[![TypeScript](https://img.shields.io/badge/typescript-5.0+-blue.svg)](https://www.typescriptlang.org/)

## ✨ Features

### 🗄️ **Multi-Database Support**
- **PostgreSQL** - Full driver with pg_stat analysis and pg_dump/pg_restore
- **MySQL/MariaDB** - Complete INFORMATION_SCHEMA support with mysqldump
- **SQLite** - File-based operations with PRAGMA analysis
- **MongoDB** - Collection and document analysis with mongodump
- **Redis** - Key-value analysis and memory usage tracking

### 📊 **Storage Analysis Dashboard**
- **Comprehensive Metrics** - Per-database and per-table size analysis
- **Visual Charts** - Interactive bar charts, pie charts, and treemaps
- **Growth Trends** - Historical storage growth tracking
- **Index Analysis** - Index size and bloat estimation
- **Export Capabilities** - PNG charts and CSV data export

### 🔐 **Secure Connection Management**
- **Encrypted Storage** - All credentials encrypted using libsodium
- **SSH Tunneling** - Secure remote database access
- **Safe Mode** - Blocks dangerous operations by default
- **Connection Testing** - One-click connection validation

### 🖥️ **Advanced Query Console**
- **Monaco Editor** - Professional code editor with syntax highlighting
- **Multi-Tab Interface** - Manage multiple queries simultaneously
- **Query History** - Persistent query history and favorites
- **Explain Plans** - SQL query optimization analysis
- **Safe Execution** - User-controlled write operations

### 💾 **Backup & Restore System**
- **Local Backups** - File-based backup with compression
- **S3 Integration** - Cloud backup with S3-compatible storage
- **Scheduled Backups** - Cron-based backup scheduling
- **Encrypted Storage** - Secure backup encryption
- **One-Click Restore** - Easy database restoration

### 🎨 **Modern User Interface**
- **Auto Theme Detection** - System light/dark theme support
- **Professional Design** - Clean, modern interface with shadcn/ui
- **Responsive Layout** - Optimized for all screen sizes
- **Cross-Platform** - Native look and feel on Windows, macOS, and Linux

### 🐳 **Demo Environment**
- **Docker Stack** - Complete demo database environment
- **Pre-seeded Data** - Sample data for immediate testing
- **All Database Types** - PostgreSQL, MySQL, MongoDB, Redis
- **Easy Setup** - Single command to start demo stack

## 🚀 Quick Start

### Prerequisites
- Node.js 18.0.0 or higher
- pnpm 8.0.0 or higher
- Docker (for demo stack)

### Installation

#### Method 1: Development Setup (Recommended)

1. **Clone Repository**
   ```bash
   git clone https://github.com/voxhash/db-storage-manager.git
   cd db-storage-manager
   ```

2. **Install Dependencies**
   ```bash
   pnpm install
   ```

3. **Start Demo Stack (Optional)**
   ```bash
   pnpm demo:up
   ```

4. **Run Application**
   ```bash
   pnpm dev
   ```

#### Method 2: Production Build

1. **Build Application**
   ```bash
   pnpm build
   ```

2. **Create Distribution**
   ```bash
   pnpm dist
   ```

3. **Install Application**
   - **Windows**: Run the generated installer
   - **macOS**: Mount the DMG and drag to Applications
   - **Linux**: Install the appropriate package (.deb, .rpm, .pkg.tar.zst)

## 🎯 Usage

### Adding Database Connections

1. **Open Application** - Launch DB Storage Manager
2. **Add Connection** - Click "Add Connection" button
3. **Configure Settings** - Enter database details and credentials
4. **Test Connection** - Verify connectivity before saving
5. **Save Connection** - Encrypted credentials are stored securely

### Analyzing Storage

1. **Select Connection** - Choose from your saved connections
2. **Run Analysis** - Click "Analyze" to scan database storage
3. **View Results** - Explore detailed storage metrics and charts
4. **Export Data** - Save charts and data for reporting

### Managing Backups

1. **Create Backup** - Select connection and backup settings
2. **Schedule Backups** - Set up automated backup schedules
3. **Monitor Backups** - View backup history and status
4. **Restore Data** - One-click restore with confirmation

### Using Query Console

1. **Open Console** - Navigate to Query Console tab
2. **Write Queries** - Use Monaco editor for SQL/NoSQL queries
3. **Execute Safely** - Safe mode blocks dangerous operations
4. **View Results** - Analyze query results and explain plans

## 🔧 Configuration

### Settings

Access via **Settings** menu:
- **Theme** - Light, dark, or system theme
- **Language** - Internationalization support
- **Safe Mode** - Enable/disable write operations
- **Notifications** - System notification preferences
- **Telemetry** - Anonymous usage statistics (disabled by default)

### Security

- **Encrypted Storage** - All credentials encrypted with libsodium
- **Local-Only** - No external data transmission
- **Safe Mode** - Prevents accidental data modification
- **SSH Tunneling** - Secure remote connections

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
DB_Storage_Manager/
├── apps/
│   ├── desktop/              # Main Electron application
│   │   ├── electron/         # Main process and database drivers
│   │   ├── src/              # React frontend
│   │   └── public/           # Static assets
│   └── demo/                 # Demo database stack
├── docs/                     # Documentation
├── .github/workflows/        # CI/CD pipelines
└── package.json              # Root configuration
```

### Available Scripts

```bash
# Development
pnpm dev                     # Start development server
pnpm build                   # Build application
pnpm dist                    # Create distribution packages

# Demo Stack
pnpm demo:up                 # Start demo databases
pnpm demo:down               # Stop demo databases

# Testing
pnpm test                    # Run tests
pnpm test:ui                 # Run tests with UI
pnpm test:coverage           # Run tests with coverage

# Code Quality
pnpm lint                    # Run linter
pnpm lint:fix                # Fix linting issues
pnpm typecheck               # Type checking
pnpm format                  # Format code
```

### Building from Source

1. **Clone Repository**
   ```bash
   git clone https://github.com/voxhash/db-storage-manager.git
   cd db-storage-manager
   ```

2. **Install Dependencies**
   ```bash
   pnpm install
   ```

3. **Build Application**
   ```bash
   pnpm build
   ```

4. **Create Distribution**
   ```bash
   pnpm dist
   ```

## 🔧 Troubleshooting

### Common Issues

**Application won't start:**
- Ensure Node.js 18+ is installed
- Run `pnpm install` to install dependencies
- Check system requirements

**Database connection fails:**
- Verify database credentials
- Check network connectivity
- Ensure database server is running

**Backup operations fail:**
- Check disk space availability
- Verify backup directory permissions
- Ensure database is accessible

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

- **Electron** - Cross-platform desktop framework
- **React** - Modern UI library
- **TypeScript** - Type-safe development
- **shadcn/ui** - Beautiful UI components
- **Database Drivers** - pg, mysql2, better-sqlite3, mongodb, redis
- **Community** - Feedback and contributions

---

**Made with ❤️ by VoxHash**

*DB Storage Manager - Professional database management made simple!* 🗄️✨