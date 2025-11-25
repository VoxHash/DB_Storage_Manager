# 🚀 Getting Started with DB Storage Manager

## Prerequisites

- **Python** 3.10 or higher
- **pip** or **pipenv**

## Quick Setup

### 1. Clone and Install
```bash
git clone https://github.com/voxhash/db-storage-manager.git
cd db-storage-manager
```

### 2. Create Virtual Environment (Recommended)
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Run Application
```bash
python -m db_storage_manager.main
```

## First Steps

### 1. Add a Database Connection
1. Click "Connections" tab in the application
2. Click "Add Connection" button
3. Select your database type (PostgreSQL, MySQL, SQLite, MongoDB, or Redis)
4. Enter connection details:
   - **Name**: A friendly name for this connection
   - **Host**: Database server address
   - **Port**: Database port (defaults provided)
   - **Database**: Database name
   - **Username**: Database username
   - **Password**: Database password
5. Click "Test Connection" to verify connectivity
6. Click "OK" to save the connection (credentials are encrypted)

### 2. Analyze Storage
1. Navigate to "Dashboard" tab
2. Select a connection from the dropdown
3. Click "Analyze" to scan database storage
4. View detailed metrics:
   - Total database size
   - Table count and sizes
   - Index information
   - Largest tables
5. Export data if needed (planned feature)

### 3. Use Query Console
1. Navigate to "Query Console" tab
2. Select a connection from the dropdown
3. Write your SQL/NoSQL queries in the editor
4. Toggle "Safe Mode" (enabled by default) to control write operations
5. Click "Execute" to run the query
6. View results in the table below
7. Review explain plans for optimization (if available)

### 4. Create Backups
1. Go to "Backups" tab
2. Select a connection
3. Choose backup adapter (Local, S3, or Google Drive)
4. Configure backup settings:
   - Compression (gzip)
   - Encryption (optional)
5. Click "Create Backup"
6. Monitor backup progress
7. View backup history

### 5. Schedule Backups
1. Go to "Backups" tab
2. Navigate to "Scheduled Backups" sub-tab
3. Click "Add Schedule"
4. Configure schedule:
   - Name: Descriptive name
   - Interval: Minutes between backups
   - Adapter: Local, S3, or Google Drive
   - Connections: All or specific connections
5. Enable/disable as needed
6. Monitor scheduled backups


## Configuration

### Settings
Access via **Settings** tab:
- **Theme**: Light, dark, or system theme
- **Language**: Internationalization support (en, es, fr, de)
- **Safe Mode**: Enable/disable write operations
- **Auto Connect**: Automatically connect on startup
- **Notifications**: System notification preferences
- **Telemetry**: Anonymous usage statistics (disabled by default)

### Security
- All credentials are encrypted with cryptography (Fernet)
- Master key is generated per installation
- Safe mode prevents accidental data modification
- SSH tunneling for secure remote connections (planned)

### Backup Configuration

#### Local Backups
- Default location: `~/.config/db-storage-manager/backups/`
- Supports compression (gzip)
- Supports encryption

#### S3 Backups
- Requires AWS credentials or S3-compatible service
- Configure bucket name and region
- Optional bucket prefix

#### Google Drive Backups
- Requires Google Service Account credentials
- Configure folder ID (optional)
- Automatic file management

## Troubleshooting

### Common Issues

**Application won't start:**
- Verify Python 3.10+ is installed: `python --version`
- Check dependencies: `pip list`
- Reinstall dependencies: `pip install -r requirements.txt --force-reinstall`
- Check system requirements

**Database connection fails:**
- Verify database credentials
- Check network connectivity
- Ensure database server is running
- Check firewall settings
- Verify port numbers

**Analysis fails:**
- Ensure database is accessible
- Check user permissions
- Verify database type compatibility
- Review error messages

**Backup fails:**
- Check disk space availability
- Verify backup directory permissions
- Ensure database is accessible
- Check adapter configuration (S3/Google Drive credentials)

**PyQt6 installation issues:**
- **Linux**: `sudo apt-get install python3-pyqt6` or `sudo yum install python3-qt6`
- **macOS**: `brew install pyqt6`
- **Windows**: Usually works with pip, but may need Visual C++ Redistributable

**Import errors:**
- Ensure virtual environment is activated
- Reinstall dependencies: `pip install -r requirements.txt`
- Check Python version compatibility

### Getting Help
- Check the [README](../README.md) for detailed information
- Visit [GitHub Issues](https://github.com/voxhash/db-storage-manager/issues)
- Join [GitHub Discussions](https://github.com/voxhash/db-storage-manager/discussions)
- Review [Architecture Documentation](ARCHITECTURE.md) for technical details

## Next Steps

After getting started:
1. **Explore Features**: Try all the different tabs and features
2. **Add Connections**: Connect to your databases
3. **Analyze Storage**: Run storage analysis on your databases
4. **Create Backups**: Set up backup schedules
5. **Use Query Console**: Execute queries safely
6. **Customize Settings**: Adjust theme and preferences

## Tips

- **Safe Mode**: Keep enabled for production databases
- **Backups**: Schedule regular backups for important databases
- **Connections**: Test connections before saving
- **Performance**: Large databases may take time to analyze
- **Security**: Keep your master key secure (stored in user data directory)

---

**Made with ❤️ by VoxHash**

*DB Storage Manager - Professional database management made simple!* 🗄️✨
