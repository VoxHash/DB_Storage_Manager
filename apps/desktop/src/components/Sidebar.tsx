import React from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { 
  Home, 
  Database, 
  Settings, 
  BarChart3, 
  HardDrive,
  Terminal,
  Shield
} from 'lucide-react'

interface SidebarProps {
  currentPage: string
  onPageChange: (page: string) => void
}

const navigationItems = [
  { id: 'dashboard', label: 'Dashboard', icon: Home },
  { id: 'connections', label: 'Connections', icon: Database },
  { id: 'analytics', label: 'Analytics', icon: BarChart3 },
  { id: 'storage', label: 'Storage', icon: HardDrive },
  { id: 'query', label: 'Query Console', icon: Terminal },
  { id: 'backup', label: 'Backup & Restore', icon: Shield },
  { id: 'settings', label: 'Settings', icon: Settings },
]

export default function Sidebar({ currentPage, onPageChange }: SidebarProps) {
  return (
    <div className="w-64 bg-background border-r h-full">
      <div className="p-4">
        <div className="flex items-center space-x-2 mb-6">
          <Database className="h-6 w-6" />
          <span className="font-bold text-lg">DB Manager</span>
        </div>
        
        <nav className="space-y-1">
          {navigationItems.map((item) => {
            const Icon = item.icon
            return (
              <Button
                key={item.id}
                variant={currentPage === item.id ? "default" : "ghost"}
                className={cn(
                  "w-full justify-start",
                  currentPage === item.id && "bg-primary text-primary-foreground"
                )}
                onClick={() => onPageChange(item.id)}
              >
                <Icon className="h-4 w-4 mr-2" />
                {item.label}
              </Button>
            )
          })}
        </nav>
      </div>
    </div>
  )
}