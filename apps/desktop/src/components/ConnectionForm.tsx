import React, { useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ConnectionConfig } from '@/lib/hooks/useConnections'
import { generateId } from '@/lib/utils'
import { 
  Database, 
  TestTube, 
  Save, 
  X, 
  Eye, 
  EyeOff,
  FolderOpen,
  Key,
  Server
} from 'lucide-react'

interface ConnectionFormProps {
  connection?: ConnectionConfig
  onSave: (connection: ConnectionConfig) => void
  onCancel: () => void
  onTest?: (connection: ConnectionConfig) => Promise<{ success: boolean; error?: string }>
}

export function ConnectionForm({ connection, onSave, onCancel, onTest }: ConnectionFormProps) {
  const [formData, setFormData] = useState<ConnectionConfig>({
    id: connection?.id || generateId(),
    name: connection?.name || '',
    type: connection?.type || 'postgresql',
    host: connection?.host || 'localhost',
    port: connection?.port || 5432,
    database: connection?.database || '',
    username: connection?.username || '',
    password: connection?.password || '',
    filePath: connection?.filePath || '',
    connectionString: connection?.connectionString || '',
    sshTunnel: connection?.sshTunnel
  })

  const [showPassword, setShowPassword] = useState(false)
  const [showSSH, setShowSSH] = useState(!!connection?.sshTunnel)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ success: boolean; error?: string } | null>(null)

  const handleInputChange = (field: keyof ConnectionConfig, value: any) => {
    setFormData(prev => ({ ...prev, [field]: value }))
  }

  const handleSSHChange = (field: keyof NonNullable<ConnectionConfig['sshTunnel']>, value: any) => {
    setFormData(prev => ({
      ...prev,
      sshTunnel: {
        ...prev.sshTunnel,
        [field]: value
      } as ConnectionConfig['sshTunnel']
    }))
  }

  const handleTestConnection = async () => {
    if (!onTest) return

    setTesting(true)
    setTestResult(null)

    try {
      const result = await onTest(formData)
      setTestResult(result)
    } catch (error) {
      setTestResult({ success: false, error: 'Test failed' })
    } finally {
      setTesting(false)
    }
  }

  const handleSave = () => {
    if (!formData.name.trim()) return
    onSave(formData)
  }

  const handleFileSelect = async () => {
    try {
      const result = await window.electronAPI.showOpenDialog({
        properties: ['openFile'],
        filters: [
          { name: 'SQLite Database', extensions: ['db', 'sqlite', 'sqlite3'] },
          { name: 'All Files', extensions: ['*'] }
        ]
      })
      if (!result.canceled && result.filePaths.length > 0) {
        handleInputChange('filePath', result.filePaths[0])
      }
    } catch (error) {
      console.error('Failed to select file:', error)
    }
  }

  const getDefaultPort = (type: string) => {
    switch (type) {
      case 'postgresql': return 5432
      case 'mysql': return 3306
      case 'mongodb': return 27017
      case 'redis': return 6379
      default: return 5432
    }
  }

  const isSQLite = formData.type === 'sqlite'
  const isMongoDB = formData.type === 'mongodb'
  const isRedis = formData.type === 'redis'

  return (
    <Card className="w-full max-w-2xl">
      <CardHeader>
        <CardTitle className="flex items-center space-x-2">
          <Database className="h-5 w-5" />
          <span>{connection ? 'Edit Connection' : 'Add New Connection'}</span>
        </CardTitle>
        <CardDescription>
          Configure your database connection settings
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <Tabs defaultValue="basic" className="w-full">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="basic">Basic Settings</TabsTrigger>
            <TabsTrigger value="advanced">Advanced</TabsTrigger>
          </TabsList>

          <TabsContent value="basic" className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="name">Connection Name</Label>
                <Input
                  id="name"
                  value={formData.name}
                  onChange={(e) => handleInputChange('name', e.target.value)}
                  placeholder="My Database"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="type">Database Type</Label>
                <Select value={formData.type} onValueChange={(value) => {
                  handleInputChange('type', value)
                  handleInputChange('port', getDefaultPort(value))
                }}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="postgresql">PostgreSQL</SelectItem>
                    <SelectItem value="mysql">MySQL/MariaDB</SelectItem>
                    <SelectItem value="sqlite">SQLite</SelectItem>
                    <SelectItem value="mongodb">MongoDB</SelectItem>
                    <SelectItem value="redis">Redis</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            {!isSQLite && (
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="host">Host</Label>
                  <Input
                    id="host"
                    value={formData.host}
                    onChange={(e) => handleInputChange('host', e.target.value)}
                    placeholder="localhost"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="port">Port</Label>
                  <Input
                    id="port"
                    type="number"
                    value={formData.port}
                    onChange={(e) => handleInputChange('port', parseInt(e.target.value))}
                    placeholder="5432"
                  />
                </div>
              </div>
            )}

            {isSQLite && (
              <div className="space-y-2">
                <Label htmlFor="filePath">Database File</Label>
                <div className="flex space-x-2">
                  <Input
                    id="filePath"
                    value={formData.filePath}
                    onChange={(e) => handleInputChange('filePath', e.target.value)}
                    placeholder="Select SQLite database file..."
                  />
                  <Button variant="outline" onClick={handleFileSelect}>
                    <FolderOpen className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            )}

            {!isRedis && (
              <div className="space-y-2">
                <Label htmlFor="database">Database Name</Label>
                <Input
                  id="database"
                  value={formData.database}
                  onChange={(e) => handleInputChange('database', e.target.value)}
                  placeholder={isMongoDB ? "Database name (optional)" : "Database name"}
                />
              </div>
            )}

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="username">Username</Label>
                <Input
                  id="username"
                  value={formData.username}
                  onChange={(e) => handleInputChange('username', e.target.value)}
                  placeholder="Username"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="password">Password</Label>
                <div className="relative">
                  <Input
                    id="password"
                    type={showPassword ? 'text' : 'password'}
                    value={formData.password}
                    onChange={(e) => handleInputChange('password', e.target.value)}
                    placeholder="Password"
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="absolute right-0 top-0 h-full px-3 py-2 hover:bg-transparent"
                    onClick={() => setShowPassword(!showPassword)}
                  >
                    {showPassword ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </Button>
                </div>
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="connectionString">Connection String (Optional)</Label>
              <Input
                id="connectionString"
                value={formData.connectionString}
                onChange={(e) => handleInputChange('connectionString', e.target.value)}
                placeholder="Override individual settings with connection string"
              />
            </div>
          </TabsContent>

          <TabsContent value="advanced" className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <Label htmlFor="ssh-tunnel">SSH Tunnel</Label>
                <p className="text-sm text-muted-foreground">
                  Connect through SSH tunnel for secure access
                </p>
              </div>
              <Switch
                id="ssh-tunnel"
                checked={showSSH}
                onCheckedChange={setShowSSH}
              />
            </div>

            {showSSH && (
              <div className="space-y-4 p-4 border rounded-lg">
                <div className="flex items-center space-x-2 text-sm font-medium">
                  <Server className="h-4 w-4" />
                  <span>SSH Tunnel Configuration</span>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="ssh-host">SSH Host</Label>
                    <Input
                      id="ssh-host"
                      value={formData.sshTunnel?.host || ''}
                      onChange={(e) => handleSSHChange('host', e.target.value)}
                      placeholder="ssh.example.com"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="ssh-port">SSH Port</Label>
                    <Input
                      id="ssh-port"
                      type="number"
                      value={formData.sshTunnel?.port || 22}
                      onChange={(e) => handleSSHChange('port', parseInt(e.target.value))}
                      placeholder="22"
                    />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="ssh-username">SSH Username</Label>
                    <Input
                      id="ssh-username"
                      value={formData.sshTunnel?.username || ''}
                      onChange={(e) => handleSSHChange('username', e.target.value)}
                      placeholder="SSH username"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="ssh-password">SSH Password</Label>
                    <Input
                      id="ssh-password"
                      type="password"
                      value={formData.sshTunnel?.password || ''}
                      onChange={(e) => handleSSHChange('password', e.target.value)}
                      placeholder="SSH password"
                    />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="ssh-key">SSH Private Key (Optional)</Label>
                  <Input
                    id="ssh-key"
                    value={formData.sshTunnel?.privateKey || ''}
                    onChange={(e) => handleSSHChange('privateKey', e.target.value)}
                    placeholder="Path to private key file"
                  />
                </div>
              </div>
            )}
          </TabsContent>
        </Tabs>

        {/* Test Result */}
        {testResult && (
          <div className={`p-3 rounded-lg border ${
            testResult.success 
              ? 'bg-green-50 border-green-200 text-green-800' 
              : 'bg-red-50 border-red-200 text-red-800'
          }`}>
            <div className="flex items-center space-x-2">
              {testResult.success ? (
                <Database className="h-4 w-4" />
              ) : (
                <X className="h-4 w-4" />
              )}
              <span className="text-sm font-medium">
                {testResult.success ? 'Connection successful!' : 'Connection failed'}
              </span>
            </div>
            {testResult.error && (
              <p className="text-sm mt-1">{testResult.error}</p>
            )}
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center justify-end space-x-2">
          <Button variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          {onTest && (
            <Button
              variant="outline"
              onClick={handleTestConnection}
              disabled={testing || !formData.name.trim()}
            >
              {testing ? (
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-current" />
              ) : (
                <TestTube className="h-4 w-4 mr-2" />
              )}
              Test Connection
            </Button>
          )}
          <Button
            onClick={handleSave}
            disabled={!formData.name.trim()}
          >
            <Save className="h-4 w-4 mr-2" />
            Save Connection
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
