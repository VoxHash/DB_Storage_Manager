export interface ConnectionConfig {
  id: string
  name: string
  type: 'postgresql' | 'mysql' | 'sqlite' | 'mongodb' | 'redis'
  host: string
  port: number
  database: string
  username: string
  password: string
  createdAt: string
}

const STORAGE_KEY = 'db-manager-connections'

export function saveConnections(connections: ConnectionConfig[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(connections))
    console.log('Connections saved to localStorage:', connections.length)
  } catch (error) {
    console.error('Failed to save connections:', error)
  }
}

export function loadConnections(): ConnectionConfig[] {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      const connections = JSON.parse(stored)
      console.log('Connections loaded from localStorage:', connections.length)
      return connections
    }
  } catch (error) {
    console.error('Failed to load connections:', error)
  }
  return []
}

export function addConnection(connection: Omit<ConnectionConfig, 'id' | 'createdAt'>): ConnectionConfig {
  const newConnection: ConnectionConfig = {
    ...connection,
    id: Date.now().toString(),
    createdAt: new Date().toISOString()
  }
  
  const connections = loadConnections()
  connections.push(newConnection)
  saveConnections(connections)
  
  console.log('Connection added:', newConnection.name)
  return newConnection
}

export function deleteConnection(id: string): void {
  const connections = loadConnections()
  const filtered = connections.filter(conn => conn.id !== id)
  saveConnections(filtered)
  console.log('Connection deleted:', id)
}
