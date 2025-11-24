import React from 'react'
import { Button } from '@/components/ui/button'
import { Bell, User, Settings, Database } from 'lucide-react'

interface HeaderProps {
  onSettingsClick: () => void
}

export default function Header({ onSettingsClick }: HeaderProps) {
  const handleNotificationClick = () => {
    console.log('Notification bell clicked')
    if (Notification.permission === 'granted') {
      new Notification('DB Storage Manager', {
        body: 'This is a test notification!'
      })
    } else if (Notification.permission !== 'denied') {
      Notification.requestPermission().then(permission => {
        if (permission === 'granted') {
          new Notification('DB Storage Manager', {
            body: 'Notifications enabled!'
          })
        }
      })
    }
  }

  const handleUserClick = () => {
    console.log('User menu clicked')
    alert('User menu functionality coming soon!')
  }

  return (
    <header className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container flex h-14 items-center">
        <div className="mr-4 flex">
          <div className="flex items-center space-x-2">
            <Database className="h-6 w-6" />
            <span className="font-bold">DB Storage Manager</span>
          </div>
        </div>
        
        <div className="flex flex-1 items-center justify-between space-x-2 md:justify-end">
          <div className="w-full flex-1 md:w-auto md:flex-none">
            {/* Navigation could go here */}
          </div>
          
          <nav className="flex items-center space-x-2">
            <Button
              variant="ghost"
              size="icon"
              onClick={handleNotificationClick}
              className="h-9 w-9"
            >
              <Bell className="h-4 w-4" />
            </Button>
            
            <Button
              variant="ghost"
              size="icon"
              onClick={onSettingsClick}
              className="h-9 w-9"
            >
              <Settings className="h-4 w-4" />
            </Button>
            
            <Button
              variant="ghost"
              size="icon"
              onClick={handleUserClick}
              className="h-9 w-9"
            >
              <User className="h-4 w-4" />
            </Button>
          </nav>
        </div>
      </div>
    </header>
  )
}