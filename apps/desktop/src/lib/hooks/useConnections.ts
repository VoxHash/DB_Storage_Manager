import { useState, useEffect } from 'react'

export interface ConnectionConfig {
  id: string
  name: string
  type: 'postgresql' | 'mysql' | 'sqlite' | 'mongodb' | 'redis'
  host?: string
  port?: number
  database?: string
  username?: string
  password?: string
  filePath?: string
  connectionString?: string
  sshTunnel?: {
    host: string
    port: number
    username: string
    password?: string
    privateKey?: string
  }
}

export function useConnections() {
  const [connections, setConnections] = useState<ConnectionConfig[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadConnections()
  }, [])

  const loadConnections = async () => {
    try {
      if (!window.electronAPI) {
        console.warn('electronAPI not available, using mock data')
        setConnections([])
        return
      }
      const result = await window.electronAPI.getConnections()
      setConnections(result)
    } catch (error) {
      console.error('Failed to load connections:', error)
    } finally {
      setLoading(false)
    }
  }

  const saveConnections = async (newConnections: ConnectionConfig[]) => {
    try {
      if (!window.electronAPI) {
        console.warn('electronAPI not available, cannot save connections')
        return false
      }
      const result = await window.electronAPI.saveConnections(newConnections)
      if (result.success) {
        setConnections(newConnections)
        return true
      }
      return false
    } catch (error) {
      console.error('Failed to save connections:', error)
      return false
    }
  }

  const addConnection = async (connection: ConnectionConfig) => {
    const newConnections = [...connections, connection]
    return await saveConnections(newConnections)
  }

  const updateConnection = async (id: string, updates: Partial<ConnectionConfig>) => {
    const newConnections = connections.map(conn => 
      conn.id === id ? { ...conn, ...updates } : conn
    )
    return await saveConnections(newConnections)
  }

  const deleteConnection = async (id: string) => {
    const newConnections = connections.filter(conn => conn.id !== id)
    return await saveConnections(newConnections)
  }

  const testConnection = async (connection: ConnectionConfig) => {
    try {
      const result = await window.electronAPI.testConnection(connection)
      return result
    } catch (error) {
      return { success: false, error: 'Failed to test connection' }
    }
  }

  return {
    connections,
    loading,
    addConnection,
    updateConnection,
    deleteConnection,
    testConnection,
    refresh: loadConnections
  }
}
