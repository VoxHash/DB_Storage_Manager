# 🏗️ DB Storage Manager Architecture

## Overview

DB Storage Manager is a cross-platform desktop application built with Electron, React, and TypeScript. It follows a secure, modular architecture designed for professional database management.

## Architecture Components

### 🖥️ Desktop Application (Electron)
- **Main Process**: Node.js backend handling database operations
- **Renderer Process**: React frontend for user interface
- **Preload Script**: Secure IPC communication bridge

### 🗄️ Database Layer
- **Driver Factory**: Centralized database driver management
- **Connection Pooling**: Efficient database connections
- **Query Execution**: Safe query execution with validation
- **Analysis Engine**: Storage analysis and metrics calculation

### 🔐 Security Layer
- **Encrypted Storage**: libsodium-based credential encryption
- **Safe Mode**: Prevents dangerous operations by default
- **SSH Tunneling**: Secure remote database access
- **Input Validation**: Comprehensive input sanitization

### 🎨 User Interface
- **React Components**: Modular UI components with shadcn/ui
- **State Management**: React Context for global state
- **Routing**: React Router for navigation
- **Theming**: System theme detection with manual override

## Technology Stack

### Frontend
- **React 18**: Modern UI library with hooks
- **TypeScript**: Type-safe development
- **Tailwind CSS**: Utility-first styling
- **shadcn/ui**: Professional component library
- **Monaco Editor**: VS Code-like editing experience
- **Recharts**: Data visualization

### Backend
- **Electron 31**: Cross-platform desktop framework
- **Node.js**: JavaScript runtime
- **Database Drivers**: pg, mysql2, better-sqlite3, mongodb, redis
- **libsodium**: Cryptographic library
- **ssh2**: SSH tunneling support

### Build Tools
- **Vite**: Fast build tool and dev server
- **TypeScript**: Static type checking
- **ESLint**: Code quality
- **Prettier**: Code formatting
- **Vitest**: Testing framework

## Data Flow

### 1. Connection Management
```
User Input → Connection Form → Validation → Encryption → Secure Storage
```

### 2. Database Analysis
```
Connection → Driver → Query Execution → Data Processing → Visualization
```

### 3. Query Execution
```
Query Input → Validation → Safe Mode Check → Execution → Results
```

### 4. Backup Process
```
Connection → Data Export → Compression → Encryption → Storage
```

## Security Architecture

### Credential Storage
- All credentials encrypted with libsodium
- Master key generated per installation
- Local-only storage (no external transmission)

### Safe Mode
- Blocks dangerous operations by default
- User can override with explicit confirmation
- Prevents accidental data modification

### SSH Tunneling
- Secure remote database access
- Encrypted connection through SSH
- Support for key-based authentication

## Performance Considerations

### Database Connections
- Connection pooling for efficiency
- Lazy loading for large datasets
- Background processing for heavy operations

### UI Performance
- React optimization with memoization
- Lazy loading for components
- Efficient re-rendering strategies

### Memory Management
- Smart resource cleanup
- Efficient data structures
- Background garbage collection

## Extension Points

### Plugin System (Future)
- Plugin API for extensions
- Third-party plugin support
- Plugin marketplace

### Custom Drivers (Future)
- Driver interface for new databases
- Custom analysis modules
- Integration with external tools

## Deployment

### Cross-Platform
- Windows: NSIS installer
- macOS: DMG package
- Linux: DEB, RPM, and Arch packages

### Development
- Hot reload for development
- TypeScript compilation
- Automated testing

---

**Made with ❤️ by VoxHash**

*DB Storage Manager - Professional database management made simple!* 🗄️✨