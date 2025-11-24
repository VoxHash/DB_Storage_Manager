import { BackupAdapter, BackupInfo, BackupOptions, S3Config } from './types'
// import { S3Client, PutObjectCommand, GetObjectCommand, ListObjectsV2Command, DeleteObjectCommand } from '@aws-sdk/client-s3'
import { generateId } from '../../src/lib/utils'

export class S3BackupAdapter implements BackupAdapter {
  private s3Client: S3Client
  private config: S3Config

  constructor(config: S3Config) {
    this.config = config
    this.s3Client = new S3Client({
      endpoint: config.endpoint,
      region: config.region || 'us-east-1',
      credentials: {
        accessKeyId: config.accessKeyId,
        secretAccessKey: config.secretAccessKey
      }
    })
  }

  async createBackup(options: BackupOptions): Promise<BackupInfo> {
    const backupId = generateId()
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
    const fileName = `${options.connectionName}_${timestamp}.backup`
    const key = this.getS3Key(fileName)
    
    try {
      // Create backup data based on database type
      const backupData = await this.createBackupData(options)
      
      // Upload to S3
      const uploadCommand = new PutObjectCommand({
        Bucket: this.config.bucket,
        Key: key,
        Body: backupData,
        Metadata: {
          'backup-id': backupId,
          'connection-id': options.connectionId,
          'database-type': options.databaseType,
          'created-at': new Date().toISOString(),
          'compression': options.compression || 'none',
          'encryption': String(options.encryption || false)
        }
      })

      await this.s3Client.send(uploadCommand)

      const backupInfo: BackupInfo = {
        id: backupId,
        name: fileName,
        path: key,
        size: backupData.length,
        createdAt: new Date(),
        status: 'completed',
        metadata: {
          bucket: this.config.bucket,
          key: key,
          compression: options.compression || 'none',
          encryption: options.encryption || false,
          databaseType: options.databaseType,
          connectionId: options.connectionId
        }
      }

      // Save backup metadata
      await this.saveBackupMetadata(backupInfo)

      return backupInfo
    } catch (error) {
      throw new Error(`S3 backup failed: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  }

  async restoreBackup(backupInfo: BackupInfo): Promise<void> {
    try {
      const getCommand = new GetObjectCommand({
        Bucket: this.config.bucket,
        Key: backupInfo.path
      })

      const response = await this.s3Client.send(getCommand)
      const backupData = await response.Body?.transformToByteArray()
      
      if (!backupData) {
        throw new Error('No backup data received from S3')
      }

      // Restore based on database type
      await this.restoreBackupData(backupInfo, Buffer.from(backupData))
    } catch (error) {
      throw new Error(`S3 restore failed: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  }

  async listBackups(): Promise<BackupInfo[]> {
    try {
      const listCommand = new ListObjectsV2Command({
        Bucket: this.config.bucket,
        Prefix: this.config.pathPrefix || 'backups/',
        MaxKeys: 1000
      })

      const response = await this.s3Client.send(listCommand)
      const backups: BackupInfo[] = []

      if (response.Contents) {
        for (const object of response.Contents) {
          if (object.Key?.endsWith('.backup')) {
            try {
              const metadata = await this.getObjectMetadata(object.Key)
              if (metadata) {
                backups.push(metadata)
              }
            } catch (error) {
              console.warn(`Failed to load metadata for ${object.Key}:`, error)
            }
          }
        }
      }

      return backups.sort((a, b) => b.createdAt.getTime() - a.createdAt.getTime())
    } catch (error) {
      console.error('Failed to list S3 backups:', error)
      return []
    }
  }

  async deleteBackup(backupId: string): Promise<void> {
    try {
      const backups = await this.listBackups()
      const backup = backups.find(b => b.id === backupId)
      
      if (backup) {
        // Delete the backup file
        const deleteCommand = new DeleteObjectCommand({
          Bucket: this.config.bucket,
          Key: backup.path
        })
        await this.s3Client.send(deleteCommand)

        // Delete metadata file
        const metadataKey = backup.path.replace('.backup', '.json')
        const deleteMetadataCommand = new DeleteObjectCommand({
          Bucket: this.config.bucket,
          Key: metadataKey
        })
        await this.s3Client.send(deleteMetadataCommand)
      }
    } catch (error) {
      throw new Error(`Failed to delete S3 backup: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  }

  async validateOptions(options: BackupOptions): Promise<boolean> {
    try {
      // Test S3 connection by listing objects
      const listCommand = new ListObjectsV2Command({
        Bucket: this.config.bucket,
        MaxKeys: 1
      })
      await this.s3Client.send(listCommand)
      return true
    } catch (error) {
      return false
    }
  }

  private getS3Key(fileName: string): string {
    const prefix = this.config.pathPrefix || 'backups/'
    return `${prefix}${fileName}`
  }

  private async createBackupData(options: BackupOptions): Promise<Buffer> {
    // This would create actual backup data based on database type
    // For now, return a placeholder
    const data = {
      type: options.databaseType,
      connectionId: options.connectionId,
      timestamp: new Date().toISOString(),
      data: 'Backup data placeholder'
    }
    
    return Buffer.from(JSON.stringify(data, null, 2))
  }

  private async restoreBackupData(backupInfo: BackupInfo, data: Buffer): Promise<void> {
    // This would restore actual backup data based on database type
    console.log(`Restoring ${backupInfo.metadata?.databaseType} backup from S3...`)
  }

  private async saveBackupMetadata(backupInfo: BackupInfo): Promise<void> {
    const metadataKey = backupInfo.path.replace('.backup', '.json')
    const metadataCommand = new PutObjectCommand({
      Bucket: this.config.bucket,
      Key: metadataKey,
      Body: JSON.stringify(backupInfo, null, 2),
      ContentType: 'application/json'
    })

    await this.s3Client.send(metadataCommand)
  }

  private async getObjectMetadata(key: string): Promise<BackupInfo | null> {
    try {
      const metadataKey = key.replace('.backup', '.json')
      const getCommand = new GetObjectCommand({
        Bucket: this.config.bucket,
        Key: metadataKey
      })

      const response = await this.s3Client.send(getCommand)
      const data = await response.Body?.transformToString()
      
      if (data) {
        return JSON.parse(data)
      }
      return null
    } catch (error) {
      return null
    }
  }
}
