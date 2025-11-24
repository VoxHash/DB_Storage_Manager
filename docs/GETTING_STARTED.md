# 🚀 Getting Started with DB Storage Manager

## Prerequisites

- **Node.js** 18.0.0 or higher
- **pnpm** 8.0.0 or higher
- **Docker** (for demo stack)

## Quick Setup

### 1. Clone and Install
```bash
git clone https://github.com/voxhash/db-storage-manager.git
cd db-storage-manager
pnpm install
```

### 2. Start Demo Stack (Optional)
```bash
pnpm demo:up
```

### 3. Run Application
```bash
pnpm dev
```

## First Steps

### 1. Add a Database Connection
1. Click "Add Connection" in the dashboard
2. Select your database type
3. Enter connection details
4. Test the connection
5. Save the connection

### 2. Analyze Storage
1. Select a connection from the dashboard
2. Click "Analyze" to scan storage
3. View detailed metrics and charts
4. Export data if needed

### 3. Use Query Console
1. Navigate to Query Console
2. Write your SQL/NoSQL queries
3. Execute safely (safe mode enabled by default)
4. View results and explain plans

### 4. Create Backups
1. Go to Backups section
2. Select a connection
3. Configure backup settings
4. Create or schedule backups

## Demo Environment

The demo stack includes:
- **PostgreSQL** on port 5432
- **MySQL** on port 3306
- **MongoDB** on port 27017
- **Redis** on port 6379

All databases come with pre-seeded sample data.

## Configuration

### Settings
- **Theme**: Light, dark, or system
- **Language**: Internationalization support
- **Safe Mode**: Enable/disable write operations
- **Notifications**: System notification preferences

### Security
- All credentials are encrypted with libsodium
- Safe mode prevents accidental data modification
- SSH tunneling for secure remote connections

## Troubleshooting

### Common Issues
- **Connection fails**: Check credentials and network
- **Analysis fails**: Ensure database is accessible
- **Backup fails**: Check disk space and permissions
- **App won't start**: Verify Node.js version and dependencies

### Getting Help
- Check the [README](../README.md) for detailed information
- Visit [GitHub Issues](https://github.com/voxhash/db-storage-manager/issues)
- Join [GitHub Discussions](https://github.com/voxhash/db-storage-manager/discussions)

---

**Made with ❤️ by VoxHash**

*DB Storage Manager - Professional database management made simple!* 🗄️✨