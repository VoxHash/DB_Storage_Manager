import React, { useState, useEffect, useRef } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ConnectionConfig } from '@/lib/hooks/useConnections'
import { formatDuration } from '@/lib/utils'
import { 
  Database, 
  Play, 
  Loader2, 
  Shield, 
  ShieldOff,
  History,
  Trash2,
  Download
} from 'lucide-react'

interface QueryProps {
  connections: ConnectionConfig[]
}

interface QueryResult {
  columns: string[]
  rows: any[]
  rowCount: number
  executionTime: number
  explainPlan?: any
}

interface QueryHistory {
  id: string
  query: string
  timestamp: Date
  connectionId: string
  executionTime: number
  rowCount: number
}

export function Query({ connections }: QueryProps) {
  const [selectedConnection, setSelectedConnection] = useState<string>('')
  const [query, setQuery] = useState<string>('')
  const [result, setResult] = useState<QueryResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [safeMode, setSafeMode] = useState(true)
  const [history, setHistory] = useState<QueryHistory[]>([])
  const [activeTab, setActiveTab] = useState('query')
  const editorRef = useRef<HTMLTextAreaElement>(null)

  const loadHistory = () => {
    const saved = localStorage.getItem('query-history')
    if (saved) {
      setHistory(JSON.parse(saved).map((h: any) => ({
        ...h,
        timestamp: new Date(h.timestamp)
      })))
    }
  }

  const saveHistory = (newHistory: QueryHistory[]) => {
    setHistory(newHistory)
    localStorage.setItem('query-history', JSON.stringify(newHistory))
  }

  const addToHistory = (query: string, connectionId: string, executionTime: number, rowCount: number) => {
    const newEntry: QueryHistory = {
      id: Date.now().toString(),
      query,
      timestamp: new Date(),
      connectionId,
      executionTime,
      rowCount
    }
    const newHistory = [newEntry, ...history.slice(0, 49)] // Keep last 50 queries
    saveHistory(newHistory)
  }

  const executeQuery = async () => {
    if (!selectedConnection || !query.trim()) return

    const connection = connections.find(c => c.id === selectedConnection)
    if (!connection) return

    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const result = await window.electronAPI.executeQuery(connection, query.trim(), safeMode)
      if (result.success) {
        setResult(result.data)
        addToHistory(query.trim(), selectedConnection, result.data.executionTime, result.data.rowCount)
      } else {
        setError(result.error || 'Query execution failed')
      }
    } catch (err) {
      setError('Failed to execute query')
    } finally {
      setLoading(false)
    }
  }

  const clearQuery = () => {
    setQuery('')
    setResult(null)
    setError(null)
    if (editorRef.current) {
      editorRef.current.focus()
    }
  }

  const loadHistoryQuery = (historyItem: QueryHistory) => {
    setQuery(historyItem.query)
    setActiveTab('query')
    if (editorRef.current) {
      editorRef.current.focus()
    }
  }

  const deleteHistoryItem = (id: string) => {
    const newHistory = history.filter(h => h.id !== id)
    saveHistory(newHistory)
  }

  const clearHistory = () => {
    saveHistory([])
  }

  const exportResults = () => {
    if (!result) return

    const csvContent = [
      result.columns.join(','),
      ...result.rows.map(row => 
        result.columns.map(col => 
          typeof row[col] === 'string' && row[col].includes(',') 
            ? `"${row[col]}"` 
            : row[col]
        ).join(',')
      )
    ].join('\n')

    const blob = new Blob([csvContent], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `query-results-${Date.now()}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  useEffect(() => {
    loadHistory()
  }, [])

  useEffect(() => {
    // Load sample queries based on connection type
    if (selectedConnection) {
      const connection = connections.find(c => c.id === selectedConnection)
      if (connection) {
        switch (connection.type) {
          case 'postgresql':
            setQuery('SELECT * FROM information_schema.tables LIMIT 10;')
            break
          case 'mysql':
            setQuery('SHOW TABLES;')
            break
          case 'sqlite':
            setQuery('SELECT name FROM sqlite_master WHERE type="table";')
            break
          case 'mongodb':
            setQuery(JSON.stringify({
              collection: 'users',
              operation: 'find',
              filter: {},
              limit: 10
            }, null, 2))
            break
          case 'redis':
            setQuery('KEYS *')
            break
        }
      }
    }
  }, [selectedConnection])

  if (connections.length === 0) {
    return (
      <div className="p-6">
        <div className="text-center py-12">
          <Database className="mx-auto h-12 w-12 text-muted-foreground" />
          <h3 className="mt-4 text-lg font-semibold">No Database Connections</h3>
          <p className="mt-2 text-muted-foreground">
            Add a database connection to start running queries.
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
          <h1 className="text-3xl font-bold">Query Console</h1>
          <p className="text-muted-foreground">
            Execute queries and explore your database
          </p>
        </div>
        <div className="flex items-center space-x-4">
          <Select value={selectedConnection} onValueChange={setSelectedConnection}>
            <SelectTrigger className="w-64">
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
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
        <TabsList>
          <TabsTrigger value="query">Query Editor</TabsTrigger>
          <TabsTrigger value="history">History</TabsTrigger>
        </TabsList>

        <TabsContent value="query" className="space-y-4">
          {/* Query Editor */}
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>Query Editor</CardTitle>
                  <CardDescription>
                    Write and execute database queries
                  </CardDescription>
                </div>
                <div className="flex items-center space-x-4">
                  <div className="flex items-center space-x-2">
                    <Switch
                      id="safe-mode"
                      checked={safeMode}
                      onCheckedChange={setSafeMode}
                    />
                    <Label htmlFor="safe-mode" className="flex items-center space-x-1">
                      {safeMode ? <Shield className="h-4 w-4" /> : <ShieldOff className="h-4 w-4" />}
                      <span>Safe Mode</span>
                    </Label>
                  </div>
                  <Button onClick={executeQuery} disabled={loading || !selectedConnection || !query.trim()}>
                    {loading ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <Play className="mr-2 h-4 w-4" />
                    )}
                    Execute
                  </Button>
                  <Button variant="outline" onClick={clearQuery}>
                    Clear
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <textarea
                ref={editorRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Enter your query here..."
                className="w-full h-64 p-4 border rounded-md font-mono text-sm resize-none focus:outline-none focus:ring-2 focus:ring-ring"
                style={{ fontFamily: 'Monaco, Menlo, "Ubuntu Mono", monospace' }}
              />
            </CardContent>
          </Card>

          {/* Error Message */}
          {error && (
            <Card className="border-destructive">
              <CardContent className="pt-6">
                <div className="flex items-center space-x-2 text-destructive">
                  <Database className="h-5 w-5" />
                  <span>{error}</span>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Results */}
          {result && (
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle>Query Results</CardTitle>
                    <CardDescription>
                      {result.rowCount} rows in {formatDuration(result.executionTime)}
                    </CardDescription>
                  </div>
                  <Button variant="outline" onClick={exportResults}>
                    <Download className="mr-2 h-4 w-4" />
                    Export CSV
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                <div className="overflow-auto max-h-96">
                  <table className="w-full border-collapse">
                    <thead>
                      <tr className="border-b">
                        {result.columns.map((column) => (
                          <th key={column} className="text-left p-2 font-medium">
                            {column}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {result.rows.map((row, index) => (
                        <tr key={index} className="border-b hover:bg-muted/50">
                          {result.columns.map((column) => (
                            <td key={column} className="p-2 text-sm">
                              {row[column] !== null && row[column] !== undefined 
                                ? String(row[column]) 
                                : <span className="text-muted-foreground">NULL</span>
                              }
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="history" className="space-y-4">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>Query History</CardTitle>
                  <CardDescription>
                    {history.length} queries executed
                  </CardDescription>
                </div>
                {history.length > 0 && (
                  <Button variant="outline" onClick={clearHistory}>
                    <Trash2 className="mr-2 h-4 w-4" />
                    Clear History
                  </Button>
                )}
              </div>
            </CardHeader>
            <CardContent>
              {history.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  No queries executed yet
                </div>
              ) : (
                <div className="space-y-2">
                  {history.map((item) => (
                    <div
                      key={item.id}
                      className="flex items-center justify-between p-3 border rounded-lg hover:bg-accent"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center space-x-2 mb-1">
                          <Database className="h-4 w-4 text-muted-foreground" />
                          <span className="text-sm font-medium">
                            {connections.find(c => c.id === item.connectionId)?.name || 'Unknown'}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            {item.timestamp.toLocaleString()}
                          </span>
                        </div>
                        <div className="text-sm text-muted-foreground font-mono truncate">
                          {item.query}
                        </div>
                        <div className="text-xs text-muted-foreground mt-1">
                          {item.rowCount} rows • {formatDuration(item.executionTime)}
                        </div>
                      </div>
                      <div className="flex items-center space-x-2">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => loadHistoryQuery(item)}
                        >
                          Load
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => deleteHistoryItem(item.id)}
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
    </div>
  )
}
