import React, { useState, useEffect } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Plus, Database, HardDrive, Table, TrendingUp, Trash2, Play } from 'lucide-react'
import { useI18n } from '@/lib/i18n/useI18n'
import { ConnectionConfig, loadConnections, deleteConnection, addConnection } from '@/lib/storage/connections'

export default function Dashboard() {
  const { t } = useI18n()
  const [showAddConnection, setShowAddConnection] = useState(false)
  const [connections, setConnections] = useState<ConnectionConfig[]>([])
  const [connectionStatus, setConnectionStatus] = useState<Record<string, 'disconnected' | 'connecting' | 'connected' | 'error'>>({})
  const [storageData, setStorageData] = useState<Record<string, any>>({})

  useEffect(() => {
    const savedConnections = loadConnections()
    setConnections(savedConnections)
    // Initialize all connections as disconnected
    const status: Record<string, 'disconnected' | 'connecting' | 'connected' | 'error'> = {}
    savedConnections.forEach(conn => {
      status[conn.id] = 'disconnected'
    })
    setConnectionStatus(status)
  }, [])

  const handleAddConnection = () => {
    setShowAddConnection(true)
    console.log('Add Connection clicked - opening modal')
  }

  const handleDeleteConnection = (id: string) => {
    deleteConnection(id)
    setConnections(loadConnections())
    // Remove from status tracking
    const newStatus = { ...connectionStatus }
    delete newStatus[id]
    setConnectionStatus(newStatus)
  }

  const handleConnectionSaved = () => {
    const newConnections = loadConnections()
    setConnections(newConnections)
    setShowAddConnection(false)
    // Initialize new connections as disconnected
    const newStatus = { ...connectionStatus }
    newConnections.forEach(conn => {
      if (!newStatus[conn.id]) {
        newStatus[conn.id] = 'disconnected'
      }
    })
    setConnectionStatus(newStatus)
  }

  const handleConnect = async (connection: ConnectionConfig) => {
    console.log('Connecting to:', connection.name)
    setConnectionStatus(prev => ({ ...prev, [connection.id]: 'connecting' }))
    
    try {
      // Test the connection using the Electron API
      if (window.electronAPI && window.electronAPI.testConnection) {
        const result = await window.electronAPI.testConnection(connection)
        if (result.success) {
          setConnectionStatus(prev => ({ ...prev, [connection.id]: 'connected' }))
          console.log('Connection successful!')
          
          // Try to get storage analysis
          if (window.electronAPI && window.electronAPI.analyzeDatabase) {
            try {
              const analysis = await window.electronAPI.analyzeDatabase(connection)
              console.log('Storage analysis completed:', analysis)
              
              // Handle the response structure - it might be {success: true, data: {...}} or just the data directly
              const storageInfo = analysis.success ? analysis.data : analysis
              setStorageData(prev => ({ ...prev, [connection.id]: storageInfo }))
            } catch (error) {
              console.warn('Storage analysis failed:', error)
            }
          }
        } else {
          setConnectionStatus(prev => ({ ...prev, [connection.id]: 'error' }))
          console.error('Connection failed:', result.error)
        }
      } else {
        // Fallback: simulate connection for demo
        setTimeout(() => {
          setConnectionStatus(prev => ({ ...prev, [connection.id]: 'connected' }))
          // Mock storage data
          setStorageData(prev => ({
            ...prev,
            [connection.id]: {
              totalSize: 0, // Real size will be 0 for non-existent DB
              tableCount: 0,
              rowCount: 0,
              largestTable: null
            }
          }))
        }, 1000)
      }
    } catch (error) {
      console.error('Connection error:', error)
      setConnectionStatus(prev => ({ ...prev, [connection.id]: 'error' }))
    }
  }

  const handleDisconnect = (connectionId: string) => {
    setConnectionStatus(prev => ({ ...prev, [connectionId]: 'disconnected' }))
    setStorageData(prev => {
      const newData = { ...prev }
      delete newData[connectionId]
      return newData
    })
  }

  // Calculate real totals from connected databases
  const connectedConnections = connections.filter(conn => connectionStatus[conn.id] === 'connected')
  const totalStorage = Object.values(storageData).reduce((sum, data) => sum + (data?.totalSize || 0), 0)
  const totalDatabases = connectedConnections.length
  const totalTables = Object.values(storageData).reduce((sum, data) => sum + (data?.tableCount || 0), 0)
  
  // Debug logging
  console.log('Connected connections:', connectedConnections.length)
  console.log('Storage data:', storageData)
  console.log('Total storage calculated:', totalStorage)
  console.log('Total tables calculated:', totalTables)

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">{t('databaseStorageManager')}</h1>
          <p className="text-muted-foreground">
            {t('monitorAndManage')}
          </p>
        </div>
        <Button onClick={handleAddConnection} className="flex items-center gap-2">
          <Plus className="h-4 w-4" />
          {t('addConnection')}
        </Button>
      </div>

      {/* Stats Overview */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">{t('totalStorage')}</CardTitle>
            <HardDrive className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {totalStorage > 0 ? `${(totalStorage / 1024 / 1024).toFixed(2)} MB` : '0 MB'}
            </div>
            <p className="text-xs text-muted-foreground">
              {connectedConnections.length === 0 ? 'No active connections' : `Across ${connectedConnections.length} connected database${connectedConnections.length > 1 ? 's' : ''}`}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">{t('databases')}</CardTitle>
            <Database className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{totalDatabases}</div>
            <p className="text-xs text-muted-foreground">
              {connectedConnections.length === 0 ? 'No active connections' : 'Connected'}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">{t('tables')}</CardTitle>
            <Table className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{totalTables}</div>
            <p className="text-xs text-muted-foreground">
              {connectedConnections.length === 0 ? 'No active connections' : 'From connected databases'}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">{t('growth')}</CardTitle>
            <TrendingUp className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">0%</div>
            <p className="text-xs text-muted-foreground">
              {connections.length === 0 ? 'No data' : 'This week'}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Connections List */}
      {connections.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>{t('connections')}</CardTitle>
            <CardDescription>
              {connections.length} {t('databases').toLowerCase()} configured
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {connections.map((connection) => {
                const status = connectionStatus[connection.id] || 'disconnected'
                const storage = storageData[connection.id]
                const isConnected = status === 'connected'
                const isConnecting = status === 'connecting'
                const hasError = status === 'error'
                
                return (
                  <div key={connection.id} className="flex items-center justify-between p-3 border rounded-lg">
                    <div className="flex items-center space-x-3">
                      <Database className={`h-5 w-5 ${isConnected ? 'text-green-500' : hasError ? 'text-red-500' : 'text-muted-foreground'}`} />
                      <div>
                        <div className="font-medium">{connection.name}</div>
                        <div className="text-sm text-muted-foreground">
                          {connection.type.toUpperCase()} • {connection.host}:{connection.port}
                        </div>
                        {isConnected && storage && (
                          <div className="text-xs text-muted-foreground mt-1">
                            Storage: {storage.totalSize ? `${(storage.totalSize / 1024 / 1024).toFixed(2)} MB` : '0 MB'} • 
                            Tables: {storage.tableCount || 0} • 
                            Rows: {storage.rowCount || 0}
                          </div>
                        )}
                        {hasError && (
                          <div className="text-xs text-red-500 mt-1">
                            Connection failed
                          </div>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center space-x-2">
                      {isConnected ? (
                        <Button 
                          size="sm" 
                          variant="outline"
                          onClick={() => handleDisconnect(connection.id)}
                        >
                          Disconnect
                        </Button>
                      ) : (
                        <Button 
                          size="sm" 
                          variant="outline"
                          onClick={() => handleConnect(connection)}
                          disabled={isConnecting}
                        >
                          {isConnecting ? (
                            <>
                              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-900 mr-1"></div>
                              Connecting...
                            </>
                          ) : (
                            <>
                              <Play className="h-4 w-4 mr-1" />
                              Connect
                            </>
                          )}
                        </Button>
                      )}
                      <Button 
                        size="sm" 
                        variant="outline"
                        onClick={() => handleDeleteConnection(connection.id)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                )
              })}
            </div>
          </CardContent>
        </Card>
      ) : (
        /* Empty State */
        <Card>
          <CardHeader>
            <CardTitle>{t('noConnections')}</CardTitle>
            <CardDescription>
              {t('getStarted')}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-center py-8">
              <Database className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
              <h3 className="text-lg font-semibold mb-2">{t('noConnectionsFound')}</h3>
              <p className="text-muted-foreground mb-4">
                Add a database connection to start monitoring storage usage
              </p>
              <Button onClick={handleAddConnection} className="flex items-center gap-2">
                <Plus className="h-4 w-4" />
                {t('addFirstConnection')}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Add Connection Modal */}
      {showAddConnection && (
        <AddConnectionModal 
          onClose={() => setShowAddConnection(false)}
          onSave={handleConnectionSaved}
        />
      )}
    </div>
  )
}

interface AddConnectionModalProps {
  onClose: () => void
  onSave: () => void
}

function AddConnectionModal({ onClose, onSave }: AddConnectionModalProps) {
  const { t } = useI18n()
  const [formData, setFormData] = useState({
    name: '',
    type: 'postgresql' as const,
    host: 'localhost',
    port: 5432,
    database: '',
    username: '',
    password: ''
  })

  const handleSave = () => {
    if (!formData.name || !formData.database || !formData.username) {
      alert('Please fill in all required fields')
      return
    }

    addConnection(formData)
    console.log('Connection saved!')
    onSave()
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white dark:bg-gray-800 rounded-lg p-6 w-full max-w-md mx-4">
        <h2 className="text-xl font-semibold mb-4">{t('addDatabaseConnection')}</h2>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-2">{t('databaseType')}</label>
            <select 
              className="w-full p-2 border rounded-md"
              value={formData.type}
              onChange={(e) => setFormData({...formData, type: e.target.value as any})}
            >
              <option value="postgresql">PostgreSQL</option>
              <option value="mysql">MySQL</option>
              <option value="sqlite">SQLite</option>
              <option value="mongodb">MongoDB</option>
              <option value="redis">Redis</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium mb-2">Connection Name</label>
            <input 
              type="text" 
              className="w-full p-2 border rounded-md" 
              placeholder="My Database"
              value={formData.name}
              onChange={(e) => setFormData({...formData, name: e.target.value})}
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-2">{t('host')}</label>
            <input 
              type="text" 
              className="w-full p-2 border rounded-md" 
              placeholder="localhost"
              value={formData.host}
              onChange={(e) => setFormData({...formData, host: e.target.value})}
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-2">{t('port')}</label>
            <input 
              type="number" 
              className="w-full p-2 border rounded-md" 
              placeholder="5432"
              value={formData.port}
              onChange={(e) => setFormData({...formData, port: parseInt(e.target.value)})}
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-2">{t('databaseName')}</label>
            <input 
              type="text" 
              className="w-full p-2 border rounded-md" 
              placeholder="mydb"
              value={formData.database}
              onChange={(e) => setFormData({...formData, database: e.target.value})}
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-2">{t('username')}</label>
            <input 
              type="text" 
              className="w-full p-2 border rounded-md" 
              placeholder="username"
              value={formData.username}
              onChange={(e) => setFormData({...formData, username: e.target.value})}
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-2">{t('password')}</label>
            <input 
              type="password" 
              className="w-full p-2 border rounded-md" 
              placeholder="password"
              value={formData.password}
              onChange={(e) => setFormData({...formData, password: e.target.value})}
            />
          </div>
        </div>
        <div className="flex gap-2 mt-6">
          <Button 
            onClick={onClose}
            variant="outline"
            className="flex-1"
          >
            {t('cancel')}
          </Button>
          <Button 
            onClick={handleSave}
            className="flex-1"
          >
            {t('saveConnection')}
          </Button>
        </div>
      </div>
    </div>
  )
}