import { app, BrowserWindow, ipcMain, dialog, shell } from 'electron'
import { join } from 'path'
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs'
import { AutoStartupManager } from './autoStartup'
import { TelemetryManager } from './telemetry'

// Security configuration
process.env.ELECTRON_DISABLE_SECURITY_WARNINGS = 'true'

let mainWindow: BrowserWindow | null = null
const autoStartupManager = AutoStartupManager.getInstance()
const telemetryManager = TelemetryManager.getInstance()

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
    console.log('Loading development URL: http://localhost:5178')
    console.log('Preload script path:', join(__dirname, 'preload.js'))
    mainWindow.loadURL('http://localhost:5178')
    mainWindow.webContents.openDevTools()
  } else {
    console.log('Loading production file:', join(__dirname, '../dist/index.html'))
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

app.whenReady().then(async () => {
  createWindow()

  // Initialize telemetry based on settings
  try {
    const settingsPath = join(userDataPath, 'settings.json')
    let settings = { telemetry: false }
    if (existsSync(settingsPath)) {
      const data = readFileSync(settingsPath, 'utf8')
      settings = JSON.parse(data)
    }
    await telemetryManager.initialize(settings.telemetry || false)
  } catch (error) {
    console.error('Failed to initialize telemetry:', error)
  }

  // Track app startup
  telemetryManager.trackEvent('app_startup', {
    timestamp: Date.now(),
    platform: process.platform,
    version: app.getVersion()
  })

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    }
  })
})

app.on('window-all-closed', async () => {
  // Track app shutdown
  telemetryManager.trackEvent('app_shutdown', {
    timestamp: Date.now()
  })
  
  // Upload any pending telemetry data
  await telemetryManager.shutdown()
  
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

// Simplified database connection handlers
ipcMain.handle('test-connection', async (_, connectionConfig) => {
  try {
    // Mock connection test for now
    await new Promise(resolve => setTimeout(resolve, 1000))
    return { success: true }
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' }
  }
})

ipcMain.handle('analyze-database', async (_, connectionConfig) => {
  try {
    // Mock analysis data
    const mockData = {
      totalSize: 1024 * 1024 * 100, // 100MB
      tableCount: 5,
      indexCount: 8,
      largestTable: {
        name: 'users',
        size: 1024 * 1024 * 50, // 50MB
        rowCount: 10000
      },
      tables: [
        { name: 'users', size: 1024 * 1024 * 50, rowCount: 10000, indexSize: 1024 * 1024 * 10, bloat: 0 },
        { name: 'orders', size: 1024 * 1024 * 30, rowCount: 5000, indexSize: 1024 * 1024 * 5, bloat: 0 },
        { name: 'products', size: 1024 * 1024 * 20, rowCount: 2000, indexSize: 1024 * 1024 * 3, bloat: 0 }
      ],
      indexes: [
        { name: 'idx_users_email', tableName: 'users', size: 1024 * 1024 * 5, bloat: 0 },
        { name: 'idx_orders_date', tableName: 'orders', size: 1024 * 1024 * 2, bloat: 0 }
      ],
      lastAnalyzed: new Date().toISOString()
    }
    return { success: true, data: mockData }
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' }
  }
})

ipcMain.handle('execute-query', async (_, connectionConfig, query, safeMode = true) => {
  try {
    // Mock query execution
    await new Promise(resolve => setTimeout(resolve, 500))
    
    const mockResult = {
      columns: ['id', 'name', 'email'],
      rows: [
        { id: 1, name: 'John Doe', email: 'john@example.com' },
        { id: 2, name: 'Jane Smith', email: 'jane@example.com' }
      ],
      rowCount: 2,
      executionTime: 500,
      explainPlan: null
    }
    
    return { success: true, data: mockResult }
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' }
  }
})

ipcMain.handle('get-schema', async (_, connectionConfig) => {
  try {
    // Mock schema data
    const mockSchema = {
      schemas: [
        {
          name: 'public',
          tables: [
            {
              name: 'users',
              columns: [
                { name: 'id', type: 'integer', nullable: false, defaultValue: null },
                { name: 'name', type: 'varchar', nullable: false, defaultValue: null },
                { name: 'email', type: 'varchar', nullable: false, defaultValue: null }
              ],
              indexes: [
                { name: 'idx_users_email', columns: ['email'], unique: true }
              ]
            }
          ]
        }
      ]
    }
    return { success: true, data: mockSchema }
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

// Simplified backup handlers
ipcMain.handle('create-backup', async (_, connectionConfig, backupPath) => {
  try {
    // Mock backup creation
    await new Promise(resolve => setTimeout(resolve, 2000))
    return { success: true, data: { path: backupPath, size: 1024 * 1024 * 10 } }
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' }
  }
})

ipcMain.handle('restore-backup', async (_, connectionConfig, backupPath) => {
  try {
    // Mock backup restoration
    await new Promise(resolve => setTimeout(resolve, 2000))
    return { success: true, data: {} }
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' }
  }
})

// Auto-startup handlers
ipcMain.handle('get-auto-startup-status', async () => {
  try {
    const status = await autoStartupManager.isAutoStartupEnabled()
    return { success: true, enabled: status }
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' }
  }
})

ipcMain.handle('set-auto-startup', async (_, enabled) => {
  try {
    if (enabled) {
      const result = await autoStartupManager.enable()
      return { success: result }
    } else {
      const result = await autoStartupManager.disable()
      return { success: result }
    }
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' }
  }
})

// Telemetry handlers
ipcMain.handle('get-telemetry-status', () => {
  return { enabled: telemetryManager.isTelemetryEnabled() }
})

ipcMain.handle('set-telemetry', async (_, enabled) => {
  try {
    telemetryManager.setEnabled(enabled)
    return { success: true }
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' }
  }
})

ipcMain.handle('track-telemetry-event', (_, eventName, properties) => {
  try {
    telemetryManager.trackEvent(eventName, properties)
    return { success: true }
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' }
  }
})

ipcMain.handle('track-user-action', (_, action, context) => {
  try {
    telemetryManager.trackUserAction(action, context)
    return { success: true }
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' }
  }
})

ipcMain.handle('track-error', (_, error, context) => {
  try {
    telemetryManager.trackError(error, context)
    return { success: true }
  } catch (err) {
    return { success: false, error: err instanceof Error ? err.message : 'Unknown error' }
  }
})
