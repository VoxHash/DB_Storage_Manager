import React, { useState, useEffect } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ConnectionConfig } from '@/lib/hooks/useConnections'
import { formatBytes, formatDuration } from '@/lib/utils'
import { 
  Database, 
  Download, 
  Upload, 
  HardDrive, 
  Clock,
  CheckCircle,
  AlertCircle,
  Loader2,
  Trash2,
  FolderOpen
} from 'lucide-react'

interface BackupsProps {
  connections: ConnectionConfig[]
}

interface BackupInfo {
  id: string
  connectionId: string
  connectionName: string
  path: string
  size: number
  createdAt: Date
  type: 'manual' | 'scheduled'
}

export function Backups({ connections }: BackupsProps) {
  const [selectedConnection, setSelectedConnection] = useState<string>('')
  const [backups, setBackups] = useState<BackupInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [backupPath, setBackupPath] = useState('')
  const [restorePath, setRestorePath] = useState('')
  const [activeTab, setActiveTab] = useState('create')

  const loadBackups = async () => {
    // In a real implementation, this would load from a backup index file
    // For now, we'll simulate with localStorage
    const saved = localStorage.getItem('backups')
    if (saved) {
      setBackups(JSON.parse(saved).map((b: any) => ({
        ...b,
        createdAt: new Date(b.createdAt)
      })))
    }
  }

  const saveBackups = (newBackups: BackupInfo[]) => {
    setBackups(newBackups)
    localStorage.setItem('backups', JSON.stringify(newBackups))
  }

  const createBackup = async () => {
    if (!selectedConnection || !backupPath) return

    const connection = connections.find(c => c.id === selectedConnection)
    if (!connection) return

    setLoading(true)
    setError(null)

    try {
      const result = await window.electronAPI.createBackup(connection, backupPath)
      if (result.success) {
        const newBackup: BackupInfo = {
          id: Date.now().toString(),
          connectionId: selectedConnection,
          connectionName: connection.name,
          path: result.data.path,
          size: result.data.size,
          createdAt: new Date(),
          type: 'manual'
        }
        saveBackups([newBackup, ...backups])
        setBackupPath('')
        setError(null)
      } else {
        setError(result.error || 'Backup creation failed')
      }
    } catch (err) {
      setError('Failed to create backup')
    } finally {
      setLoading(false)
    }
  }

  const restoreBackup = async (backup: BackupInfo) => {
    const connection = connections.find(c => c.id === backup.connectionId)
    if (!connection) return

    setLoading(true)
    setError(null)

    try {
      const result = await window.electronAPI.restoreBackup(connection, backup.path)
      if (result.success) {
        setError(null)
      } else {
        setError(result.error || 'Backup restore failed')
      }
    } catch (err) {
      setError('Failed to restore backup')
    } finally {
      setLoading(false)
    }
  }

  const deleteBackup = (backupId: string) => {
    const newBackups = backups.filter(b => b.id !== backupId)
    saveBackups(newBackups)
  }

  const selectBackupFile = async () => {
    try {
      const result = await window.electronAPI.showOpenDialog({
        properties: ['openFile'],
        filters: [
          { name: 'Backup Files', extensions: ['sql', 'dump', 'json', 'gz'] },
          { name: 'All Files', extensions: ['*'] }
        ]
      })
      if (!result.canceled && result.filePaths.length > 0) {
        setBackupPath(result.filePaths[0])
      }
    } catch (err) {
      setError('Failed to select backup file')
    }
  }

  const selectRestoreFile = async () => {
    try {
      const result = await window.electronAPI.showOpenDialog({
        properties: ['openFile'],
        filters: [
          { name: 'Backup Files', extensions: ['sql', 'dump', 'json', 'gz'] },
          { name: 'All Files', extensions: ['*'] }
        ]
      })
      if (!result.canceled && result.filePaths.length > 0) {
        setRestorePath(result.filePaths[0])
      }
    } catch (err) {
      setError('Failed to select restore file')
    }
  }

  useEffect(() => {
    loadBackups()
  }, [])

  if (connections.length === 0) {
    return (
      <div className="p-6">
        <div className="text-center py-12">
          <Database className="mx-auto h-12 w-12 text-muted-foreground" />
          <h3 className="mt-4 text-lg font-semibold">No Database Connections</h3>
          <p className="mt-2 text-muted-foreground">
            Add a database connection to create and manage backups.
          </p>
          <Button className="mt-4">
            Add Connection
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Backup & Restore</h1>
          <p className="text-muted-foreground">
            Create and restore database backups
          </p>
        </div>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
        <TabsList>
          <TabsTrigger value="create">Create Backup</TabsTrigger>
          <TabsTrigger value="restore">Restore Backup</TabsTrigger>
          <TabsTrigger value="manage">Manage Backups</TabsTrigger>
        </TabsList>

        <TabsContent value="create" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Create New Backup</CardTitle>
              <CardDescription>
                Create a backup of your database
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="connection">Database Connection</Label>
                <Select value={selectedConnection} onValueChange={setSelectedConnection}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select a connection" />
                  </SelectTrigger>
                  <SelectContent>
                    {connections.map((connection) => (
                      <SelectItem key={connection.id} value={connection.id}>
                        <div className="flex items-center space-x-2">
                          <div className={`h-2 w-2 rounded-full ${
                            connection.type === 'postgresql' && 'bg-blue-500',
                            connection.type === 'mysql' && 'bg-orange-500',
                            connection.type === 'sqlite' && 'bg-green-500',
                            connection.type === 'mongodb' && 'bg-green-600',
                            connection.type === 'redis' && 'bg-red-500'
                          }`} />
                          <span>{connection.name}</span>
                        </div>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="backup-path">Backup Path</Label>
                <div className="flex space-x-2">
                  <Input
                    id="backup-path"
                    value={backupPath}
                    onChange={(e) => setBackupPath(e.target.value)}
                    placeholder="Choose backup file location..."
                  />
                  <Button variant="outline" onClick={selectBackupFile}>
                    <FolderOpen className="h-4 w-4" />
                  </Button>
                </div>
              </div>

              <Button 
                onClick={createBackup} 
                disabled={loading || !selectedConnection || !backupPath}
                className="w-full"
              >
                {loading ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Download className="mr-2 h-4 w-4" />
                )}
                Create Backup
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="restore" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Restore from Backup</CardTitle>
              <CardDescription>
                Restore a database from a backup file
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="restore-path">Backup File</Label>
                <div className="flex space-x-2">
                  <Input
                    id="restore-path"
                    value={restorePath}
                    onChange={(e) => setRestorePath(e.target.value)}
                    placeholder="Choose backup file to restore..."
                  />
                  <Button variant="outline" onClick={selectRestoreFile}>
                    <FolderOpen className="h-4 w-4" />
                  </Button>
                </div>
              </div>

              <div className="p-4 bg-destructive/10 border border-destructive/20 rounded-lg">
                <div className="flex items-center space-x-2 text-destructive">
                  <AlertCircle className="h-5 w-5" />
                  <span className="font-medium">Warning</span>
                </div>
                <p className="text-sm text-destructive mt-2">
                  Restoring a backup will overwrite all existing data in the target database. 
                  This action cannot be undone.
                </p>
              </div>

              <Button 
                variant="destructive"
                onClick={() => {
                  if (restorePath) {
                    // In a real implementation, you'd need to select the target connection
                    // and show a confirmation dialog
                    setError('Restore functionality requires target connection selection')
                  }
                }}
                disabled={!restorePath}
                className="w-full"
              >
                <Upload className="mr-2 h-4 w-4" />
                Restore Backup
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="manage" className="space-y-4">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>Backup History</CardTitle>
                  <CardDescription>
                    {backups.length} backup{backups.length !== 1 ? 's' : ''} available
                  </CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {backups.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  No backups created yet
                </div>
              ) : (
                <div className="space-y-2">
                  {backups.map((backup) => (
                    <div
                      key={backup.id}
                      className="flex items-center justify-between p-4 border rounded-lg hover:bg-accent"
                    >
                      <div className="flex items-center space-x-4">
                        <HardDrive className="h-8 w-8 text-muted-foreground" />
                        <div>
                          <div className="font-medium">{backup.connectionName}</div>
                          <div className="text-sm text-muted-foreground">
                            {backup.path}
                          </div>
                          <div className="text-xs text-muted-foreground">
                            {formatBytes(backup.size)} • {backup.createdAt.toLocaleString()}
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center space-x-2">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => restoreBackup(backup)}
                          disabled={loading}
                        >
                          <Upload className="h-4 w-4" />
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => deleteBackup(backup.id)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Error Message */}
      {error && (
        <Card className="border-destructive">
          <CardContent className="pt-6">
            <div className="flex items-center space-x-2 text-destructive">
              <AlertCircle className="h-5 w-5" />
              <span>{error}</span>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
