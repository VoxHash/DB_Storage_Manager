# 🏗️ DB Storage Manager Architecture

## Overview

DB Storage Manager is a cross-platform desktop application built with Python and PyQt6. It follows a secure, modular architecture designed for professional database management.

## Architecture Components

### 🖥️ Desktop Application (PyQt6)
- **Main Window**: QMainWindow with tabbed interface
- **Widgets**: Modular PyQt6 widgets for each feature
- **Threading**: QThread for background database operations
- **Event Loop**: Qt event loop for async operations

### 🗄️ Database Layer
- **Connection Factory**: Centralized database connection management
- **Async Operations**: asyncio for non-blocking database operations
- **Query Execution**: Safe query execution with validation
- **Analysis Engine**: Storage analysis and metrics calculation
- **Driver Abstraction**: Unified interface for all database types

### 🔐 Security Layer
- **Encrypted Storage**: cryptography (Fernet) for credential encryption
- **Safe Mode**: Prevents dangerous operations by default
- **SSH Tunneling**: Secure remote database access (planned)
- **Input Validation**: Comprehensive input sanitization
- **Master Key**: Per-installation encryption key

### 🎨 User Interface
- **PyQt6 Components**: Native Qt widgets
- **Tabbed Interface**: Main window with multiple tabs
- **Responsive Design**: Adapts to different screen sizes
- **Theme Support**: Light, dark, and system themes
- **Threading**: Background operations don't block UI

### 💾 Backup System
- **Adapter Pattern**: Pluggable backup storage adapters
- **Local Adapter**: File system backups
- **S3 Adapter**: AWS S3 and compatible services
- **Google Drive Adapter**: Google Drive integration
- **Scheduler**: Automated backup scheduling

## Technology Stack

### Frontend
- **PyQt6 6.6+**: Modern Qt framework for Python
- **PyQt6-Charts**: Data visualization (optional)
- **QThread**: Background processing
- **Qt Signals/Slots**: Event-driven architecture

### Backend
- **Python 3.10+**: Modern Python with async support
- **asyncio**: Asynchronous operations
- **Database Drivers**: 
  - psycopg2-binary (PostgreSQL)
  - pymysql (MySQL/MariaDB)
  - aiosqlite (SQLite)
  - pymongo (MongoDB)
  - redis (Redis)
- **cryptography**: Cryptographic library (Fernet)
- **paramiko**: SSH tunneling support (planned)

### Backup & Cloud
- **boto3**: AWS S3 integration
- **google-api-python-client**: Google Drive API
- **schedule**: Backup scheduling

### Build Tools
- **setuptools**: Package management
- **pytest**: Testing framework
- **black**: Code formatting
- **flake8**: Code linting
- **mypy**: Static type checking

## Data Flow

### 1. Connection Management
```
User Input → Connection Dialog → Validation → Encryption → Secure Storage
```

### 2. Database Analysis
```
Connection → Factory → Driver → Async Query → Data Processing → UI Update
```

### 3. Query Execution
```
Query Input → Validation → Safe Mode Check → Async Execution → Results → UI
```

### 4. Backup Process
```
Connection → Database Export → Compression → Encryption → Adapter → Storage
```

## Security Architecture

### Credential Storage
- All credentials encrypted with cryptography (Fernet)
- Master key generated per installation
- Stored in user data directory with restrictive permissions
- Local-only storage (no external transmission)

### Safe Mode
- Blocks dangerous operations by default
- User can override with explicit confirmation
- Prevents accidental data modification
- Validates queries before execution

### Encryption
- **Algorithm**: Fernet (symmetric encryption)
- **Key Management**: Master key stored securely
- **Key Derivation**: PBKDF2 for key generation
- **Storage**: Encrypted JSON files

## Performance Considerations

### Database Connections
- Async/await for non-blocking operations
- Connection pooling (planned)
- Lazy loading for large datasets
- Background processing for heavy operations

### UI Performance
- QThread for background operations
- Efficient widget updates
- Lazy loading for large tables
- Minimal re-rendering

### Memory Management
- Smart resource cleanup
- Efficient data structures
- Proper async context management
- Garbage collection optimization

## Module Structure

### Database Modules (`db/`)
- **base.py**: Abstract base classes and interfaces
- **factory.py**: Connection factory pattern
- **postgres.py**: PostgreSQL implementation
- **mysql.py**: MySQL/MariaDB implementation
- **sqlite.py**: SQLite implementation
- **mongo.py**: MongoDB implementation
- **redis.py**: Redis implementation

### Backup Modules (`backups/`)
- **base.py**: Backup adapter interface
- **manager.py**: Backup orchestration
- **local.py**: Local file system adapter
- **s3.py**: AWS S3 adapter
- **googledrive.py**: Google Drive adapter
- **scheduler.py**: Scheduled backup manager

### GUI Modules (`gui/`)
- **main_window.py**: Main application window
- **dashboard.py**: Storage analysis dashboard
- **connections.py**: Connection management
- **query.py**: Query console
- **backups.py**: Backup management
- **settings.py**: Application settings

### Security Modules (`security/`)
- **store.py**: Encrypted storage implementation

## Extension Points

### Plugin System (Future)
- Plugin API for extensions
- Third-party plugin support
- Plugin marketplace

### Custom Drivers (Future)
- Driver interface for new databases
- Custom analysis modules
- Integration with external tools

### Backup Adapters (Extensible)
- Implement BackupAdapter interface
- Register with BackupManager
- Support for new storage backends

## Deployment

### Cross-Platform
- **Windows**: Executable with PyInstaller (planned)
- **macOS**: Application bundle (planned)
- **Linux**: AppImage or package (planned)

### Development
- Virtual environment for isolation
- Requirements.txt for dependencies
- Setup.py for package installation
- pytest for testing

## Async Architecture

### Database Operations
- All database operations use async/await
- QThread bridges async code with Qt event loop
- Non-blocking UI during database operations
- Proper error handling and cancellation

### Backup Operations
- Async backup creation and restoration
- Progress reporting through signals
- Background processing for large backups
- Cancellation support

## Error Handling

### Database Errors
- Connection errors handled gracefully
- Query errors displayed to user
- Retry logic for transient errors
- Detailed error messages

### UI Errors
- User-friendly error dialogs
- Error logging for debugging
- Graceful degradation
- Recovery suggestions

## Testing Strategy

### Unit Tests
- Test individual modules
- Mock database connections
- Test error handling
- Test encryption/decryption

### Integration Tests
- Test full workflows
- Test with real databases (optional)
- Test backup/restore cycles
- Test UI interactions

### Performance Tests
- Test with large datasets
- Test concurrent operations
- Test memory usage
- Test response times

---

**Made with ❤️ by VoxHash**

*DB Storage Manager - Professional database management made simple!* 🗄️✨
