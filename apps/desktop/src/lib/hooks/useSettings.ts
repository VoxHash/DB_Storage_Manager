import { useState, useEffect } from 'react'

export interface Settings {
  theme: 'light' | 'dark' | 'system'
  language: string
  safeMode: boolean
  autoConnect: boolean
  notifications: boolean
  telemetry: boolean
}

const defaultSettings: Settings = {
  theme: 'system',
  language: 'en',
  safeMode: true,
  autoConnect: false,
  notifications: true,
  telemetry: false
}

export function useSettings() {
  const [settings, setSettings] = useState<Settings>(defaultSettings)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadSettings()
  }, [])

  const loadSettings = async () => {
    try {
      if (!window.electronAPI) {
        console.warn('electronAPI not available, using default settings')
        setSettings(defaultSettings)
        return
      }
      const result = await window.electronAPI.getSettings()
      setSettings({ ...defaultSettings, ...result })
    } catch (error) {
      console.error('Failed to load settings:', error)
    } finally {
      setLoading(false)
    }
  }

  const saveSettings = async (newSettings: Partial<Settings>) => {
    try {
      if (!window.electronAPI) {
        console.warn('electronAPI not available, cannot save settings')
        return false
      }
      const updatedSettings = { ...settings, ...newSettings }
      const result = await window.electronAPI.saveSettings(updatedSettings)
      if (result.success) {
        setSettings(updatedSettings)
        return true
      }
      return false
    } catch (error) {
      console.error('Failed to save settings:', error)
      return false
    }
  }

  return {
    settings,
    loading,
    saveSettings,
    refresh: loadSettings
  }
}
