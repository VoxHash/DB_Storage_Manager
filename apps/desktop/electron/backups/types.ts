export interface BackupInfo {
  id: string
  name: string
  path: string
  size: number
  createdAt: Date
  duration?: number
  status: 'pending' | 'completed' | 'failed'
  metadata?: Record<string, any>
}

export interface BackupOptions {
  connectionId: string
  connectionName: string
  databaseType: string
  backupPath: string
  compression?: 'none' | 'gzip' | 'zstd'
  encryption?: boolean
  encryptionKey?: string
  metadata?: Record<string, any>
}

export interface BackupAdapter {
  createBackup(options: BackupOptions): Promise<BackupInfo>
  restoreBackup(backupInfo: BackupInfo): Promise<void>
  listBackups(): Promise<BackupInfo[]>
  deleteBackup(backupId: string): Promise<void>
  validateOptions(options: BackupOptions): Promise<boolean>
}

export interface S3Config {
  endpoint: string
  bucket: string
  accessKeyId: string
  secretAccessKey: string
  region?: string
  pathPrefix?: string
}

export interface LocalConfig {
  basePath: string
  maxBackups?: number
  retentionDays?: number
}
