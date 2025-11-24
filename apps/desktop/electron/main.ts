import { app, BrowserWindow, ipcMain, dialog, shell } from 'electron'
import { join } from 'path'
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs'

// Security configuration
process.env.ELECTRON_DISABLE_SECURITY_WARNINGS = 'true'

let mainWindow: BrowserWindow | null = null

const isDev = process.env.NODE_ENV === 'development'
const userDataPath = app.getPath('userData')

// Ensure userData directory exists
if (!existsSync(userDataPath)) {
  mkdirSync(userDataPath, { recursive: true })
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1200,
    minHeight: 700,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: join(__dirname, 'preload.js'),
    },
    titleBarStyle: 'default',
    show: false,
    icon: join(__dirname, '../public/icon.svg'),
  })

  // Load the app
  if (isDev) {
    mainWindow.loadURL('http://localhost:5178')
    mainWindow.webContents.openDevTools()
  } else {
    mainWindow.loadFile(join(__dirname, '../dist/index.html'))
  }

  mainWindow.once('ready-to-show', () => {
    mainWindow?.show()
  })

  mainWindow.on('closed', () => {
    mainWindow = null
  })

  // Handle external links
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })
}

app.whenReady().then(() => {
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    }
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

// IPC handlers
ipcMain.handle('get-app-version', () => {
  return app.getVersion()
})

ipcMain.handle('get-user-data-path', () => {
  return userDataPath
})

ipcMain.handle('show-open-dialog', async (_, options) => {
  const result = await dialog.showOpenDialog(mainWindow!, options)
  return result
})

ipcMain.handle('show-save-dialog', async (_, options) => {
  const result = await dialog.showSaveDialog(mainWindow!, options)
  return result
})

ipcMain.handle('show-message-box', async (_, options) => {
  const result = await dialog.showMessageBox(mainWindow!, options)
  return result
})

// Database connection handlers
ipcMain.handle('test-connection', async (_, connectionConfig) => {
  try {
    // Import database modules dynamically
    const { DatabaseConnectionFactory } = await import('./db/index')
    const db = DatabaseConnectionFactory.createConnection(connectionConfig)
    await db.testConnection()
    await db.disconnect()
    return { success: true }
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' }
  }
})

ipcMain.handle('analyze-database', async (_, connectionConfig) => {
  try {
    const { DatabaseConnectionFactory } = await import('./db/index')
    const db = DatabaseConnectionFactory.createConnection(connectionConfig)
    const analysis = await db.analyzeStorage()
    await db.disconnect()
    return { success: true, data: analysis }
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' }
  }
})

ipcMain.handle('execute-query', async (_, connectionConfig, query, safeMode = true) => {
  try {
    const { DatabaseConnectionFactory } = await import('./db/index')
    const db = DatabaseConnectionFactory.createConnection(connectionConfig)
    
    if (safeMode) {
      // Check for dangerous operations
      const dangerousPatterns = [
        /INSERT\s+/i,
        /UPDATE\s+/i,
        /DELETE\s+/i,
        /DROP\s+/i,
        /ALTER\s+/i,
        /TRUNCATE\s+/i,
        /CREATE\s+/i,
        /GRANT\s+/i,
        /REVOKE\s+/i
      ]
      
      if (dangerousPatterns.some(pattern => pattern.test(query))) {
        throw new Error('Dangerous operation blocked in safe mode. Toggle "Allow writes" to enable.')
      }
    }
    
    const result = await db.executeQuery(query)
    await db.disconnect()
    return { success: true, data: result }
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' }
  }
})

ipcMain.handle('get-schema', async (_, connectionConfig) => {
  try {
    const { DatabaseConnectionFactory } = await import('./db/index')
    const db = DatabaseConnectionFactory.createConnection(connectionConfig)
    const schema = await db.getSchema()
    await db.disconnect()
    return { success: true, data: schema }
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' }
  }
})

// Settings and connections management
ipcMain.handle('get-settings', async () => {
  try {
    const settingsPath = join(userDataPath, 'settings.json')
    if (existsSync(settingsPath)) {
      const data = readFileSync(settingsPath, 'utf8')
      return JSON.parse(data)
    }
    return { theme: 'system', language: 'en' }
  } catch (error) {
    return { theme: 'system', language: 'en' }
  }
})

ipcMain.handle('save-settings', async (_, settings) => {
  try {
    const settingsPath = join(userDataPath, 'settings.json')
    writeFileSync(settingsPath, JSON.stringify(settings, null, 2))
    return { success: true }
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' }
  }
})

ipcMain.handle('get-connections', async () => {
  try {
    const connectionsPath = join(userDataPath, 'connections.json')
    if (existsSync(connectionsPath)) {
      const data = readFileSync(connectionsPath, 'utf8')
      return JSON.parse(data)
    }
    return []
  } catch (error) {
    return []
  }
})

ipcMain.handle('save-connections', async (_, connections) => {
  try {
    const connectionsPath = join(userDataPath, 'connections.json')
    writeFileSync(connectionsPath, JSON.stringify(connections, null, 2))
    return { success: true }
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' }
  }
})

// Backup handlers
ipcMain.handle('create-backup', async (_, connectionConfig, backupPath) => {
  try {
    const { DatabaseConnectionFactory } = await import('./db/index')
    const db = DatabaseConnectionFactory.createConnection(connectionConfig)
    const result = await db.createBackup(backupPath)
    await db.disconnect()
    return { success: true, data: result }
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' }
  }
})

ipcMain.handle('restore-backup', async (_, connectionConfig, backupPath) => {
  try {
    const { DatabaseConnectionFactory } = await import('./db/index')
    const db = DatabaseConnectionFactory.createConnection(connectionConfig)
    const result = await db.restoreBackup(backupPath)
    await db.disconnect()
    return { success: true, data: result }
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' }
  }
})
