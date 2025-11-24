import { expect, afterEach, beforeEach } from 'vitest'
import { cleanup } from '@testing-library/react'
import * as matchers from '@testing-library/jest-dom/matchers'

// Extend Vitest's expect with jest-dom matchers
expect.extend(matchers)

// Cleanup after each test
afterEach(() => {
  cleanup()
})

// Mock Electron API
Object.defineProperty(window, 'electronAPI', {
  value: {
    getAppVersion: () => Promise.resolve('1.0.0'),
    getUserDataPath: () => Promise.resolve('/tmp/dbsm'),
    showOpenDialog: () => Promise.resolve({ canceled: false, filePaths: [] }),
    showSaveDialog: () => Promise.resolve({ canceled: false, filePath: '' }),
    showMessageBox: () => Promise.resolve({ response: 0 }),
    testConnection: () => Promise.resolve({ success: true }),
    analyzeDatabase: () => Promise.resolve({ success: true, data: {} }),
    executeQuery: () => Promise.resolve({ success: true, data: { columns: [], rows: [], rowCount: 0, executionTime: 0 } }),
    getSchema: () => Promise.resolve({ success: true, data: { schemas: [] } }),
    getSettings: () => Promise.resolve({ theme: 'system', language: 'en' }),
    saveSettings: () => Promise.resolve({ success: true }),
    getConnections: () => Promise.resolve([]),
    saveConnections: () => Promise.resolve({ success: true }),
    createBackup: () => Promise.resolve({ success: true, data: { path: '', size: 0 } }),
    restoreBackup: () => Promise.resolve({ success: true, data: {} }),
  },
  writable: true,
})
