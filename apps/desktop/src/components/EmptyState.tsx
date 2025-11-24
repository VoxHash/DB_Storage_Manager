import React from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { 
  Database, 
  Plus, 
  Search, 
  Terminal, 
  HardDrive,
  BarChart3,
  Settings
} from 'lucide-react'

interface EmptyStateProps {
  type: 'connections' | 'dashboard' | 'explorer' | 'query' | 'backups' | 'settings'
  title: string
  description: string
  action?: {
    label: string
    onClick: () => void
  }
}

const icons = {
  connections: Database,
  dashboard: BarChart3,
  explorer: Search,
  query: Terminal,
  backups: HardDrive,
  settings: Settings
}

export function EmptyState({ type, title, description, action }: EmptyStateProps) {
  const Icon = icons[type]

  return (
    <Card>
      <CardContent className="flex flex-col items-center justify-center py-12 text-center">
        <div className="mx-auto w-16 h-16 bg-muted rounded-full flex items-center justify-center mb-4">
          <Icon className="h-8 w-8 text-muted-foreground" />
        </div>
        <h3 className="text-lg font-semibold mb-2">{title}</h3>
        <p className="text-muted-foreground mb-6 max-w-md">{description}</p>
        {action && (
          <Button onClick={action.onClick}>
            <Plus className="h-4 w-4 mr-2" />
            {action.label}
          </Button>
        )}
      </CardContent>
    </Card>
  )
}
