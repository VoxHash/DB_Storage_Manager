import { app } from 'electron'
import * as os from 'os'
import * as path from 'path'

export interface TelemetryEvent {
  id: string
  timestamp: number
  event: string
  properties: Record<string, any>
  sessionId: string
}

export interface TelemetrySession {
  sessionId: string
  startTime: number
  lastActivity: number
  events: TelemetryEvent[]
  systemInfo: {
    platform: string
    arch: string
    version: string
    appVersion: string
  }
}

export class TelemetryManager {
  private static instance: TelemetryManager
  private session: TelemetrySession | null = null
  private isEnabled: boolean = false
  private uploadUrl: string = 'https://your-vps.com/api/telemetry' // Replace with your VPS endpoint
  private uploadInterval: NodeJS.Timeout | null = null

  private constructor() {}

  static getInstance(): TelemetryManager {
    if (!TelemetryManager.instance) {
      TelemetryManager.instance = new TelemetryManager()
    }
    return TelemetryManager.instance
  }

  async initialize(enabled: boolean): Promise<void> {
    this.isEnabled = enabled
    
    if (enabled) {
      await this.startSession()
      this.startUploadInterval()
    } else {
      this.stopUploadInterval()
    }
  }

  private async startSession(): Promise<void> {
    const sessionId = this.generateSessionId()
    const now = Date.now()
    
    this.session = {
      sessionId,
      startTime: now,
      lastActivity: now,
      events: [],
      systemInfo: {
        platform: process.platform,
        arch: process.arch,
        version: os.version(),
        appVersion: app.getVersion()
      }
    }

    // Track session start
    this.trackEvent('session_start', {
      sessionId,
      timestamp: now
    })
  }

  private generateSessionId(): string {
    return `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
  }

  trackEvent(eventName: string, properties: Record<string, any> = {}): void {
    if (!this.isEnabled || !this.session) return

    const event: TelemetryEvent = {
      id: `event_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      timestamp: Date.now(),
      event: eventName,
      properties: {
        ...properties,
        // Add some basic context
        appVersion: app.getVersion(),
        platform: process.platform,
        arch: process.arch
      },
      sessionId: this.session.sessionId
    }

    this.session.events.push(event)
    this.session.lastActivity = Date.now()

    // Keep only last 1000 events to prevent memory issues
    if (this.session.events.length > 1000) {
      this.session.events = this.session.events.slice(-1000)
    }
  }

  trackUserAction(action: string, context: string = ''): void {
    this.trackEvent('user_action', {
      action,
      context,
      timestamp: Date.now()
    })
  }

  trackError(error: string, context: string = ''): void {
    this.trackEvent('error', {
      error,
      context,
      timestamp: Date.now()
    })
  }

  trackPerformance(operation: string, duration: number, success: boolean): void {
    this.trackEvent('performance', {
      operation,
      duration,
      success,
      timestamp: Date.now()
    })
  }

  trackDatabaseOperation(dbType: string, operation: string, success: boolean, duration?: number): void {
    this.trackEvent('database_operation', {
      dbType,
      operation,
      success,
      duration,
      timestamp: Date.now()
    })
  }

  private startUploadInterval(): void {
    // Upload every 5 minutes
    this.uploadInterval = setInterval(() => {
      this.uploadTelemetryData()
    }, 5 * 60 * 1000)
  }

  private stopUploadInterval(): void {
    if (this.uploadInterval) {
      clearInterval(this.uploadInterval)
      this.uploadInterval = null
    }
  }

  private async uploadTelemetryData(): Promise<void> {
    if (!this.session || this.session.events.length === 0) return

    try {
      const data = {
        session: this.session,
        timestamp: Date.now()
      }

      const response = await fetch(this.uploadUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'User-Agent': `DB-Storage-Manager/${app.getVersion()}`
        },
        body: JSON.stringify(data)
      })

      if (response.ok) {
        // Clear uploaded events
        this.session.events = []
        console.log('Telemetry data uploaded successfully')
      } else {
        console.warn('Failed to upload telemetry data:', response.status)
      }
    } catch (error) {
      console.error('Error uploading telemetry data:', error)
    }
  }

  async uploadPendingData(): Promise<void> {
    await this.uploadTelemetryData()
  }

  async shutdown(): Promise<void> {
    if (this.session) {
      this.trackEvent('session_end', {
        sessionId: this.session.sessionId,
        duration: Date.now() - this.session.startTime,
        eventCount: this.session.events.length
      })
      
      await this.uploadPendingData()
    }
    
    this.stopUploadInterval()
  }

  setEnabled(enabled: boolean): void {
    this.isEnabled = enabled
    
    if (enabled && !this.session) {
      this.startSession()
      this.startUploadInterval()
    } else if (!enabled) {
      this.stopUploadInterval()
    }
  }

  isTelemetryEnabled(): boolean {
    return this.isEnabled
  }

  getSessionInfo(): { sessionId: string; eventCount: number } | null {
    if (!this.session) return null
    
    return {
      sessionId: this.session.sessionId,
      eventCount: this.session.events.length
    }
  }
}
