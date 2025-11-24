import { contextBridge, ipcRenderer } from 'electron'

console.log('Preload script loaded successfully')

// Expose protected methods that allow the renderer process to use
// the ipcRenderer without exposing the entire object
contextBridge.exposeInMainWorld('electronAPI', {
  // App info
  getAppVersion: () => ipcRenderer.invoke('get-app-version'),
  getUserDataPath: () => ipcRenderer.invoke('get-user-data-path'),

  // Dialog methods
  showOpenDialog: (options: any) => ipcRenderer.invoke('show-open-dialog', options),
  showSaveDialog: (options: any) => ipcRenderer.invoke('show-save-dialog', options),
  showMessageBox: (options: any) => ipcRenderer.invoke('show-message-box', options),

  // Database operations
  testConnection: (connectionConfig: any) => ipcRenderer.invoke('test-connection', connectionConfig),
  analyzeDatabase: (connectionConfig: any) => ipcRenderer.invoke('analyze-database', connectionConfig),
  executeQuery: (connectionConfig: any, query: string, safeMode?: boolean) => 
    ipcRenderer.invoke('execute-query', connectionConfig, query, safeMode),
  getSchema: (connectionConfig: any) => ipcRenderer.invoke('get-schema', connectionConfig),

  // Settings and connections
  getSettings: () => ipcRenderer.invoke('get-settings'),
  saveSettings: (settings: any) => ipcRenderer.invoke('save-settings', settings),
  getConnections: () => ipcRenderer.invoke('get-connections'),
  saveConnections: (connections: any[]) => ipcRenderer.invoke('save-connections', connections),

  // Backup operations
  createBackup: (connectionConfig: any, backupPath: string) => 
    ipcRenderer.invoke('create-backup', connectionConfig, backupPath),
  restoreBackup: (connectionConfig: any, backupPath: string) => 
    ipcRenderer.invoke('restore-backup', connectionConfig, backupPath),

  // Auto-startup operations
  getAutoStartupStatus: () => {
    try {
      return ipcRenderer.invoke('get-auto-startup-status')
    } catch (error) {
      console.warn('Auto-startup not available:', error)
      return Promise.resolve({ success: false, enabled: false })
    }
  },
  setAutoStartup: (enabled: boolean) => {
    try {
      return ipcRenderer.invoke('set-auto-startup', enabled)
    } catch (error) {
      console.warn('Auto-startup not available:', error)
      return Promise.resolve({ success: false, error: 'Auto-startup not available' })
    }
  },

  // Telemetry operations
  getTelemetryStatus: () => {
    try {
      return ipcRenderer.invoke('get-telemetry-status')
    } catch (error) {
      console.warn('Telemetry not available:', error)
      return Promise.resolve({ enabled: false })
    }
  },
  setTelemetry: (enabled: boolean) => {
    try {
      return ipcRenderer.invoke('set-telemetry', enabled)
    } catch (error) {
      console.warn('Telemetry not available:', error)
      return Promise.resolve({ success: false, error: 'Telemetry not available' })
    }
  },
  trackTelemetryEvent: (eventName: string, properties: any) => {
    try {
      return ipcRenderer.invoke('track-telemetry-event', eventName, properties)
    } catch (error) {
      console.warn('Telemetry not available:', error)
      return Promise.resolve({ success: false, error: 'Telemetry not available' })
    }
  },
  trackUserAction: (action: string, context: string) => {
    try {
      return ipcRenderer.invoke('track-user-action', action, context)
    } catch (error) {
      console.warn('Telemetry not available:', error)
      return Promise.resolve({ success: false, error: 'Telemetry not available' })
    }
  },
  trackError: (error: string, context: string) => {
    try {
      return ipcRenderer.invoke('track-error', error, context)
    } catch (error) {
      console.warn('Telemetry not available:', error)
      return Promise.resolve({ success: false, error: 'Telemetry not available' })
    }
  },
})

// Type definitions for the exposed API
declare global {
  interface Window {
    electronAPI: {
      getAppVersion: () => Promise<string>
      getUserDataPath: () => Promise<string>
      showOpenDialog: (options: any) => Promise<any>
      showSaveDialog: (options: any) => Promise<any>
      showMessageBox: (options: any) => Promise<any>
      testConnection: (connectionConfig: any) => Promise<{ success: boolean; error?: string }>
      analyzeDatabase: (connectionConfig: any) => Promise<{ success: boolean; data?: any; error?: string }>
      executeQuery: (connectionConfig: any, query: string, safeMode?: boolean) => Promise<{ success: boolean; data?: any; error?: string }>
      getSchema: (connectionConfig: any) => Promise<{ success: boolean; data?: any; error?: string }>
      getSettings: () => Promise<any>
      saveSettings: (settings: any) => Promise<{ success: boolean; error?: string }>
      getConnections: () => Promise<any[]>
      saveConnections: (connections: any[]) => Promise<{ success: boolean; error?: string }>
      createBackup: (connectionConfig: any, backupPath: string) => Promise<{ success: boolean; data?: any; error?: string }>
      restoreBackup: (connectionConfig: any, backupPath: string) => Promise<{ success: boolean; data?: any; error?: string }>
      getAutoStartupStatus: () => Promise<{ success: boolean; enabled?: boolean; error?: string }>
      setAutoStartup: (enabled: boolean) => Promise<{ success: boolean; error?: string }>
      getTelemetryStatus: () => Promise<{ enabled: boolean }>
      setTelemetry: (enabled: boolean) => Promise<{ success: boolean; error?: string }>
      trackTelemetryEvent: (eventName: string, properties: any) => Promise<{ success: boolean; error?: string }>
      trackUserAction: (action: string, context: string) => Promise<{ success: boolean; error?: string }>
      trackError: (error: string, context: string) => Promise<{ success: boolean; error?: string }>
    }
  }
}
