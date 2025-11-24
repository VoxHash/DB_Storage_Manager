import { BackupAdapter, BackupInfo, BackupOptions } from './types'
import { LocalBackupAdapter } from './localAdapter'
import { S3BackupAdapter } from './s3Adapter'
import { Scheduler } from './scheduler'

export interface BackupManager {
  createBackup(adapter: BackupAdapter, options: BackupOptions): Promise<BackupInfo>
  restoreBackup(adapter: BackupAdapter, backupInfo: BackupInfo): Promise<void>
  listBackups(adapter: BackupAdapter): Promise<BackupInfo[]>
  deleteBackup(adapter: BackupAdapter, backupId: string): Promise<void>
  scheduleBackup(adapter: BackupAdapter, options: BackupOptions, cronExpression: string): Promise<void>
  cancelScheduledBackup(backupId: string): Promise<void>
}

export class DefaultBackupManager implements BackupManager {
  private scheduler: Scheduler
  private adapters: Map<string, BackupAdapter>

  constructor() {
    this.scheduler = new Scheduler()
    this.adapters = new Map()
    this.initializeAdapters()
  }

  private initializeAdapters() {
    this.adapters.set('local', new LocalBackupAdapter())
    // this.adapters.set('s3', new S3BackupAdapter())
  }

  async createBackup(adapter: BackupAdapter, options: BackupOptions): Promise<BackupInfo> {
    const startTime = Date.now()
    
    try {
      const backupInfo = await adapter.createBackup(options)
      const endTime = Date.now()
      
      return {
        ...backupInfo,
        duration: endTime - startTime,
        createdAt: new Date(),
        status: 'completed'
      }
    } catch (error) {
      throw new Error(`Backup failed: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  }

  async restoreBackup(adapter: BackupAdapter, backupInfo: BackupInfo): Promise<void> {
    try {
      await adapter.restoreBackup(backupInfo)
    } catch (error) {
      throw new Error(`Restore failed: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  }

  async listBackups(adapter: BackupAdapter): Promise<BackupInfo[]> {
    try {
      return await adapter.listBackups()
    } catch (error) {
      throw new Error(`Failed to list backups: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  }

  async deleteBackup(adapter: BackupAdapter, backupId: string): Promise<void> {
    try {
      await adapter.deleteBackup(backupId)
    } catch (error) {
      throw new Error(`Failed to delete backup: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  }

  async scheduleBackup(adapter: BackupAdapter, options: BackupOptions, cronExpression: string): Promise<void> {
    const jobId = `backup_${Date.now()}`
    
    this.scheduler.schedule(jobId, cronExpression, async () => {
      try {
        await this.createBackup(adapter, options)
        console.log(`Scheduled backup completed: ${jobId}`)
      } catch (error) {
        console.error(`Scheduled backup failed: ${jobId}`, error)
      }
    })
  }

  async cancelScheduledBackup(backupId: string): Promise<void> {
    this.scheduler.cancel(backupId)
  }

  getAdapter(type: string): BackupAdapter | undefined {
    return this.adapters.get(type)
  }
}

export { LocalBackupAdapter } from './localAdapter'
export { S3BackupAdapter } from './s3Adapter'
export { Scheduler } from './scheduler'
export * from './types'
