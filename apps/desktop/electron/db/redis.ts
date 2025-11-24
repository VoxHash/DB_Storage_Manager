import { createClient, RedisClientType } from 'redis'
import { DatabaseConnection, ConnectionConfig, StorageAnalysis, QueryResult, SchemaInfo } from './index'
import { writeFileSync } from 'fs'

export class RedisConnection extends DatabaseConnection {
  private client?: RedisClientType

  async connect(): Promise<void> {
    const connectionString = this.config.connectionString || 
      `redis://${this.config.username ? `${this.config.username}:${this.config.password}@` : ''}${this.config.host}:${this.config.port || 6379}`

    this.client = createClient({ url: connectionString })
    await this.client.connect()
    this.connected = true
  }

  async disconnect(): Promise<void> {
    if (this.client) {
      await this.client.quit()
      this.client = undefined
      this.connected = false
    }
  }

  async testConnection(): Promise<void> {
    if (!this.client) {
      await this.connect()
    }
    
    await this.client!.ping()
  }

  async analyzeStorage(): Promise<StorageAnalysis> {
    if (!this.client) {
      await this.connect()
    }

    const client = this.client!

    // Get Redis info
    const info = await client.info('memory')
    const memoryInfo = this.parseRedisInfo(info)
    const totalSize = memoryInfo.used_memory || 0

    // Get database info
    const dbInfo = await client.info('keyspace')
    const keyspaceInfo = this.parseRedisInfo(dbInfo)

    // Get all keys (this can be expensive for large databases)
    const keys = await client.keys('*')
    const keyCount = keys.length

    // Analyze key types and sizes
    const keyAnalysis = new Map<string, { count: number; totalSize: number }>()
    
    for (const key of keys.slice(0, 1000)) { // Limit to first 1000 keys for performance
      try {
        const type = await client.type(key)
        const memoryUsage = await client.memoryUsage(key)
        
        if (!keyAnalysis.has(type)) {
          keyAnalysis.set(type, { count: 0, totalSize: 0 })
        }
        
        const analysis = keyAnalysis.get(type)!
        analysis.count++
        analysis.totalSize += memoryUsage
      } catch (error) {
        // Skip keys that can't be analyzed
      }
    }

    // Convert to tables format
    const tables = Array.from(keyAnalysis.entries()).map(([type, analysis]) => ({
      name: `keys:${type}`,
      size: analysis.totalSize,
      rowCount: analysis.count,
      indexSize: 0,
      bloat: 0
    }))

    // Sort by size descending
    tables.sort((a, b) => b.size - a.size)

    const largestTable = tables.length > 0 ? tables[0] : { name: 'N/A', size: 0, rowCount: 0 }

    return {
      totalSize,
      tableCount: tables.length,
      indexCount: 0, // Redis doesn't have traditional indexes
      largestTable,
      tables,
      indexes: [], // Redis doesn't have traditional indexes
      lastAnalyzed: new Date().toISOString()
    }
  }

  async executeQuery(query: string): Promise<QueryResult> {
    if (!this.client) {
      await this.connect()
    }

    const client = this.client!
    const startTime = Date.now()

    try {
      // Parse Redis command (simplified)
      const parts = query.trim().split(' ')
      const command = parts[0].toUpperCase()
      const args = parts.slice(1)

      let result: any

      switch (command) {
        case 'GET':
          result = await client.get(args[0])
          break
        case 'SET':
          result = await client.set(args[0], args[1])
          break
        case 'KEYS':
          result = await client.keys(args[0] || '*')
          break
        case 'INFO':
          result = await client.info(args[0] || 'server')
          break
        case 'PING':
          result = await client.ping()
          break
        case 'DBSIZE':
          result = await client.dbSize()
          break
        case 'FLUSHDB':
          result = await client.flushDb()
          break
        case 'FLUSHALL':
          result = await client.flushAll()
          break
        default:
          // Try to execute as a generic command
          result = await client.sendCommand([command, ...args])
      }

      const executionTime = Date.now() - startTime

      // Format result for display
      const rows = Array.isArray(result) ? result.map(item => ({ value: item })) : [{ value: result }]
      const columns = ['value']

      return {
        columns,
        rows,
        rowCount: rows.length,
        executionTime,
        explainPlan: undefined
      }
    } catch (error) {
      throw new Error(`Redis command failed: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  }

  async getSchema(): Promise<SchemaInfo> {
    if (!this.client) {
      await this.connect()
    }

    const client = this.client!

    // Get all keys and their types
    const keys = await client.keys('*')
    const keyTypes = new Map<string, number>()

    for (const key of keys.slice(0, 1000)) { // Limit for performance
      try {
        const type = await client.type(key)
        keyTypes.set(type, (keyTypes.get(type) || 0) + 1)
      } catch (error) {
        // Skip keys that can't be analyzed
      }
    }

    // Convert to schema format
    const tables = Array.from(keyTypes.entries()).map(([type, count]) => ({
      name: `keys:${type}`,
      columns: [
        { name: 'key', type: 'string', nullable: false, defaultValue: undefined },
        { name: 'value', type: type, nullable: true, defaultValue: undefined }
      ],
      indexes: []
    }))

    return {
      schemas: [{
        name: 'default',
        tables
      }]
    }
  }

  async createBackup(backupPath: string): Promise<{ path: string; size: number }> {
    if (!this.client) {
      await this.connect()
    }

    const client = this.client!

    try {
      // Get all keys and their values
      const keys = await client.keys('*')
      const backupData: any = {
        database: this.config.database || 'default',
        keys: {}
      }

      for (const key of keys) {
        try {
          const type = await client.type(key)
          let value: any

          switch (type) {
            case 'string':
              value = await client.get(key)
              break
            case 'list':
              value = await client.lRange(key, 0, -1)
              break
            case 'set':
              value = await client.sMembers(key)
              break
            case 'zset':
              value = await client.zRangeWithScores(key, 0, -1)
              break
            case 'hash':
              value = await client.hGetAll(key)
              break
            default:
              value = null
          }

          backupData.keys[key] = { type, value }
        } catch (error) {
          // Skip keys that can't be backed up
        }
      }

      // Write backup to file
      const backupJson = JSON.stringify(backupData, null, 2)
      writeFileSync(backupPath, backupJson)

      const stats = require('fs').statSync(backupPath)
      return { path: backupPath, size: stats.size }
    } catch (error) {
      throw new Error(`Failed to create Redis backup: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  }

  async restoreBackup(backupPath: string): Promise<void> {
    if (!this.client) {
      await this.connect()
    }

    const client = this.client!

    try {
      // Read backup file
      const backupData = JSON.parse(require('fs').readFileSync(backupPath, 'utf8'))

      // Clear existing database
      await client.flushDb()

      // Restore keys
      for (const [key, keyData] of Object.entries(backupData.keys)) {
        const { type, value } = keyData as any

        switch (type) {
          case 'string':
            await client.set(key, value)
            break
          case 'list':
            if (Array.isArray(value)) {
              await client.lPush(key, ...value)
            }
            break
          case 'set':
            if (Array.isArray(value)) {
              await client.sAdd(key, ...value)
            }
            break
          case 'zset':
            if (Array.isArray(value)) {
              await client.zAdd(key, value)
            }
            break
          case 'hash':
            if (typeof value === 'object' && value !== null) {
              await client.hSet(key, value)
            }
            break
        }
      }
    } catch (error) {
      throw new Error(`Failed to restore Redis backup: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  }

  private parseRedisInfo(info: string): Record<string, any> {
    const result: Record<string, any> = {}
    const lines = info.split('\r\n')
    
    for (const line of lines) {
      if (line.includes(':')) {
        const [key, value] = line.split(':', 2)
        result[key] = isNaN(Number(value)) ? value : Number(value)
      }
    }
    
    return result
  }
}
