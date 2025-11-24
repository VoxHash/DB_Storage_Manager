import React, { useState } from 'react'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ConnectionForm } from '@/components/ConnectionForm'
import { ConnectionConfig } from '@/lib/hooks/useConnections'

interface ConnectionModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  connection?: ConnectionConfig
  onSave: (connection: ConnectionConfig) => void
  onTest?: (connection: ConnectionConfig) => Promise<{ success: boolean; error?: string }>
}

export function ConnectionModal({ 
  open, 
  onOpenChange, 
  connection, 
  onSave, 
  onTest 
}: ConnectionModalProps) {
  const [saving, setSaving] = useState(false)

  console.log('ConnectionModal render - open:', open)

  const handleSave = async (connectionData: ConnectionConfig) => {
    setSaving(true)
    try {
      await onSave(connectionData)
      onOpenChange(false)
    } catch (error) {
      console.error('Failed to save connection:', error)
    } finally {
      setSaving(false)
    }
  }

  const handleCancel = () => {
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {connection ? 'Edit Connection' : 'Add New Connection'}
          </DialogTitle>
          <DialogDescription>
            Configure your database connection settings. All credentials are encrypted and stored securely.
          </DialogDescription>
        </DialogHeader>
        <ConnectionForm
          connection={connection}
          onSave={handleSave}
          onCancel={handleCancel}
          onTest={onTest}
        />
      </DialogContent>
    </Dialog>
  )
}
