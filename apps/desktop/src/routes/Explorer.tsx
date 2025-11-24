import React, { useState, useEffect } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ConnectionConfig } from '@/lib/hooks/useConnections'
import { formatBytes, formatNumber } from '@/lib/utils'
import { 
  Database, 
  ChevronRight, 
  ChevronDown, 
  Table, 
  Key,
  Loader2
} from 'lucide-react'

interface ExplorerProps {
  connections: ConnectionConfig[]
}

interface SchemaInfo {
  schemas: Array<{
    name: string
    tables: Array<{
      name: string
      columns: Array<{
        name: string
        type: string
        nullable: boolean
        defaultValue?: any
      }>
      indexes: Array<{
        name: string
        columns: string[]
        unique: boolean
      }>
    }>
  }>
}

export function Explorer({ connections }: ExplorerProps) {
  const [selectedConnection, setSelectedConnection] = useState<string>('')
  const [schema, setSchema] = useState<SchemaInfo | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expandedSchemas, setExpandedSchemas] = useState<Set<string>>(new Set())
  const [expandedTables, setExpandedTables] = useState<Set<string>>(new Set())

  const loadSchema = async (connectionId: string) => {
    const connection = connections.find(c => c.id === connectionId)
    if (!connection) return

    setLoading(true)
    setError(null)

    try {
      const result = await window.electronAPI.getSchema(connection)
      if (result.success) {
        setSchema(result.data)
        // Auto-expand first schema
        if (result.data.schemas.length > 0) {
          setExpandedSchemas(new Set([result.data.schemas[0].name]))
        }
      } else {
        setError(result.error || 'Failed to load schema')
      }
    } catch (err) {
      setError('Failed to load schema')
    } finally {
      setLoading(false)
    }
  }

  const toggleSchema = (schemaName: string) => {
    const newExpanded = new Set(expandedSchemas)
    if (newExpanded.has(schemaName)) {
      newExpanded.delete(schemaName)
    } else {
      newExpanded.add(schemaName)
    }
    setExpandedSchemas(newExpanded)
  }

  const toggleTable = (tableKey: string) => {
    const newExpanded = new Set(expandedTables)
    if (newExpanded.has(tableKey)) {
      newExpanded.delete(tableKey)
    } else {
      newExpanded.add(tableKey)
    }
    setExpandedTables(newExpanded)
  }

  useEffect(() => {
    if (selectedConnection) {
      loadSchema(selectedConnection)
    }
  }, [selectedConnection])

  if (connections.length === 0) {
    return (
      <div className="p-6">
        <div className="text-center py-12">
          <Database className="mx-auto h-12 w-12 text-muted-foreground" />
          <h3 className="mt-4 text-lg font-semibold">No Database Connections</h3>
          <p className="mt-2 text-muted-foreground">
            Add a database connection to explore schemas and tables.
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
          <h1 className="text-3xl font-bold">Schema Explorer</h1>
          <p className="text-muted-foreground">
            Browse database schemas, tables, and indexes
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
          {selectedConnection && (
            <Button 
              onClick={() => loadSchema(selectedConnection)}
              disabled={loading}
            >
              {loading ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : null}
              Refresh
            </Button>
          )}
        </div>
      </div>

      {/* Error Message */}
      {error && (
        <div className="flex items-center space-x-2 p-4 bg-destructive/10 border border-destructive/20 rounded-lg">
          <Database className="h-5 w-5 text-destructive" />
          <span className="text-destructive">{error}</span>
        </div>
      )}

      {/* Schema Tree */}
      {schema && (
        <Card>
          <CardHeader>
            <CardTitle>Database Schema</CardTitle>
            <CardDescription>
              {schema.schemas.length} schema{schema.schemas.length !== 1 ? 's' : ''} found
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {schema.schemas.map((schemaItem) => (
                <div key={schemaItem.name} className="space-y-1">
                  <div
                    className="flex items-center space-x-2 p-2 hover:bg-accent rounded cursor-pointer"
                    onClick={() => toggleSchema(schemaItem.name)}
                  >
                    {expandedSchemas.has(schemaItem.name) ? (
                      <ChevronDown className="h-4 w-4" />
                    ) : (
                      <ChevronRight className="h-4 w-4" />
                    )}
                    <Database className="h-4 w-4" />
                    <span className="font-medium">{schemaItem.name}</span>
                    <span className="text-sm text-muted-foreground">
                      ({schemaItem.tables.length} tables)
                    </span>
                  </div>

                  {expandedSchemas.has(schemaItem.name) && (
                    <div className="ml-6 space-y-1">
                      {schemaItem.tables.map((table) => {
                        const tableKey = `${schemaItem.name}.${table.name}`
                        return (
                          <div key={tableKey} className="space-y-1">
                            <div
                              className="flex items-center space-x-2 p-2 hover:bg-accent rounded cursor-pointer"
                              onClick={() => toggleTable(tableKey)}
                            >
                              {expandedTables.has(tableKey) ? (
                                <ChevronDown className="h-4 w-4" />
                              ) : (
                                <ChevronRight className="h-4 w-4" />
                              )}
                              <Table className="h-4 w-4" />
                              <span className="font-medium">{table.name}</span>
                              <span className="text-sm text-muted-foreground">
                                ({table.columns.length} columns, {table.indexes.length} indexes)
                              </span>
                            </div>

                            {expandedTables.has(tableKey) && (
                              <div className="ml-6 space-y-2">
                                {/* Columns */}
                                <div>
                                  <h4 className="text-sm font-medium text-muted-foreground mb-2">
                                    Columns ({table.columns.length})
                                  </h4>
                                  <div className="space-y-1">
                                    {table.columns.map((column) => (
                                      <div
                                        key={column.name}
                                        className="flex items-center justify-between p-2 bg-muted/50 rounded text-sm"
                                      >
                                        <div className="flex items-center space-x-2">
                                          <span className="font-medium">{column.name}</span>
                                          <span className="text-muted-foreground">{column.type}</span>
                                          {!column.nullable && (
                                            <span className="text-xs bg-primary/10 text-primary px-1 rounded">
                                              NOT NULL
                                            </span>
                                          )}
                                        </div>
                                        {column.defaultValue && (
                                          <span className="text-xs text-muted-foreground">
                                            Default: {String(column.defaultValue)}
                                          </span>
                                        )}
                                      </div>
                                    ))}
                                  </div>
                                </div>

                                {/* Indexes */}
                                {table.indexes.length > 0 && (
                                  <div>
                                    <h4 className="text-sm font-medium text-muted-foreground mb-2">
                                      Indexes ({table.indexes.length})
                                    </h4>
                                    <div className="space-y-1">
                                      {table.indexes.map((index) => (
                                        <div
                                          key={index.name}
                                          className="flex items-center justify-between p-2 bg-muted/50 rounded text-sm"
                                        >
                                          <div className="flex items-center space-x-2">
                                            <Key className="h-3 w-3" />
                                            <span className="font-medium">{index.name}</span>
                                            <span className="text-muted-foreground">
                                              ({index.columns.join(', ')})
                                            </span>
                                          </div>
                                          {index.unique && (
                                            <span className="text-xs bg-green-100 text-green-800 px-1 rounded">
                                              UNIQUE
                                            </span>
                                          )}
                                        </div>
                                      ))}
                                    </div>
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Empty State */}
      {!selectedConnection && (
        <Card>
          <CardContent className="text-center py-12">
            <Database className="mx-auto h-12 w-12 text-muted-foreground" />
            <h3 className="mt-4 text-lg font-semibold">Select a Connection</h3>
            <p className="mt-2 text-muted-foreground">
              Choose a database connection to explore its schema.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
