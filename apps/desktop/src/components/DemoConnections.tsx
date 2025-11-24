import React from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { ConnectionConfig } from '@/lib/hooks/useConnections'
import { 
  Database, 
  Play, 
  Square, 
  CheckCircle, 
  AlertCircle,
  Loader2
} from 'lucide-react'

interface DemoConnectionsProps {
  onAddConnection: (connection: ConnectionConfig) => void
  onTestConnection: (connection: ConnectionConfig) => Promise<{ success: boolean; error?: string }>
}

const demoConnections: Omit<ConnectionConfig, 'id'>[] = [
  {
    name: 'Demo PostgreSQL',
    type: 'postgresql',
    host: 'localhost',
    port: 5432,
    database: 'demo_db',
    username: 'demo_user',
    password: 'demo_password'
  },
  {
    name: 'Demo MySQL',
    type: 'mysql',
    host: 'localhost',
    port: 3306,
    database: 'demo_db',
    username: 'demo_user',
    password: 'demo_password'
  },
  {
    name: 'Demo MongoDB',
    type: 'mongodb',
    host: 'localhost',
    port: 27017,
    database: 'demo_db',
    username: 'demo_user',
    password: 'demo_password'
  },
  {
    name: 'Demo Redis',
    type: 'redis',
    host: 'localhost',
    port: 6379
  }
]

export function DemoConnections({ onAddConnection, onTestConnection }: DemoConnectionsProps) {
  const [testing, setTesting] = React.useState<Set<string>>(new Set())
  const [testResults, setTestResults] = React.useState<Record<string, { success: boolean; error?: string }>>({})

  const handleTestConnection = async (connection: Omit<ConnectionConfig, 'id'>) => {
    const connectionWithId = { ...connection, id: `demo-${connection.type}` }
    setTesting(prev => new Set(prev).add(connection.type))
    
    try {
      const result = await onTestConnection(connectionWithId)
      setTestResults(prev => ({ ...prev, [connection.type]: result }))
    } catch (error) {
      setTestResults(prev => ({ 
        ...prev, 
        [connection.type]: { success: false, error: 'Test failed' } 
      }))
    } finally {
      setTesting(prev => {
        const newSet = new Set(prev)
        newSet.delete(connection.type)
        return newSet
      })
    }
  }

  const handleAddConnection = (connection: Omit<ConnectionConfig, 'id'>) => {
    const connectionWithId = { ...connection, id: `demo-${connection.type}-${Date.now()}` }
    onAddConnection(connectionWithId)
  }

  const getConnectionIcon = (type: string) => {
    const iconClass = "h-4 w-4"
    switch (type) {
      case 'postgresql':
        return <Database className={`${iconClass} text-blue-500`} />
      case 'mysql':
        return <Database className={`${iconClass} text-orange-500`} />
      case 'mongodb':
        return <Database className={`${iconClass} text-green-600`} />
      case 'redis':
        return <Database className={`${iconClass} text-red-500`} />
      default:
        return <Database className={`${iconClass} text-gray-500`} />
    }
  }

  const getTestStatus = (type: string) => {
    if (testing.has(type)) {
      return <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
    }
    
    const result = testResults[type]
    if (result) {
      return result.success ? (
        <CheckCircle className="h-4 w-4 text-green-500" />
      ) : (
        <AlertCircle className="h-4 w-4 text-red-500" />
      )
    }
    
    return null
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center space-x-2">
          <Play className="h-5 w-5" />
          <span>Demo Database Connections</span>
        </CardTitle>
        <CardDescription>
          Connect to the demo database stack for testing and exploration
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {demoConnections.map((connection) => (
            <div
              key={connection.type}
              className="flex items-center justify-between p-4 border rounded-lg hover:bg-accent"
            >
              <div className="flex items-center space-x-3">
                {getConnectionIcon(connection.type)}
                <div>
                  <div className="font-medium">{connection.name}</div>
                  <div className="text-sm text-muted-foreground">
                    {connection.host}:{connection.port}
                    {connection.database && ` • ${connection.database}`}
                  </div>
                  {testResults[connection.type]?.error && (
                    <div className="text-sm text-red-500 mt-1">
                      {testResults[connection.type].error}
                    </div>
                  )}
                </div>
              </div>
              <div className="flex items-center space-x-2">
                {getTestStatus(connection.type)}
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => handleTestConnection(connection)}
                  disabled={testing.has(connection.type)}
                >
                  {testing.has(connection.type) ? 'Testing...' : 'Test'}
                </Button>
                <Button
                  size="sm"
                  onClick={() => handleAddConnection(connection)}
                  disabled={testing.has(connection.type)}
                >
                  Add
                </Button>
              </div>
            </div>
          ))}
        </div>
        
        <div className="mt-6 p-4 bg-muted/50 rounded-lg">
          <h4 className="font-medium mb-2">Getting Started with Demo Stack</h4>
          <ol className="text-sm text-muted-foreground space-y-1">
            <li>1. Start the demo stack: <code className="bg-muted px-1 rounded">pnpm demo:up</code></li>
            <li>2. Wait for all services to be ready (about 30 seconds)</li>
            <li>3. Test each connection to verify connectivity</li>
            <li>4. Add the connections you want to use</li>
            <li>5. Start exploring your databases!</li>
          </ol>
        </div>
      </CardContent>
    </Card>
  )
}
