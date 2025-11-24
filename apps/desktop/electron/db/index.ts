import { PostgreSQLConnection } from './postgres'
import { MySQLConnection } from './mysql'
import { SQLiteConnection } from './sqlite'
import { MongoDBConnection } from './mongo'
import { RedisConnection } from './redis'

export interface ConnectionConfig {
  id: string
  name: string
  type: 'postgresql' | 'mysql' | 'sqlite' | 'mongodb' | 'redis'
  host?: string
  port?: number
  database?: string
  username?: string
  password?: string
  filePath?: string // For SQLite
  connectionString?: string
  sshTunnel?: {
    host: string
    port: number
    username: string
    password?: string
    privateKey?: string
  }
}

export interface StorageAnalysis {
  totalSize: number
  tableCount: number
  indexCount: number
  largestTable: {
    name: string
    size: number
    rowCount: number
  }
  tables: Array<{
    name: string
    size: number
    rowCount: number
    indexSize: number
    bloat?: number
  }>
  indexes: Array<{
    name: string
    tableName: string
    size: number
    bloat?: number
  }>
  lastAnalyzed: string
}

export interface QueryResult {
  columns: string[]
  rows: any[]
  rowCount: number
  executionTime: number
  explainPlan?: any
}

export interface SchemaInfo {
  schemas: Array<{
    name: string
    tables: Array<{
      name: string
      columns: Array<{
        name: string
        type: string
        nullable: boolean
        defaultValue?: any
      }>
      indexes: Array<{
        name: string
        columns: string[]
        unique: boolean
      }>
    }>
  }>
}

export abstract class DatabaseConnection {
  protected config: ConnectionConfig
  protected connected: boolean = false

  constructor(config: ConnectionConfig) {
    this.config = config
  }

  abstract connect(): Promise<void>
  abstract disconnect(): Promise<void>
  abstract testConnection(): Promise<void>
  abstract analyzeStorage(): Promise<StorageAnalysis>
  abstract executeQuery(query: string): Promise<QueryResult>
  abstract getSchema(): Promise<SchemaInfo>
  abstract createBackup(backupPath: string): Promise<{ path: string; size: number }>
  abstract restoreBackup(backupPath: string): Promise<void>

  isConnected(): boolean {
    return this.connected
  }

  getConfig(): ConnectionConfig {
    return this.config
  }
}

export class DatabaseConnectionFactory {
  static createConnection(config: ConnectionConfig): DatabaseConnection {
    switch (config.type) {
      case 'postgresql':
        return new PostgreSQLConnection(config)
      case 'mysql':
        return new MySQLConnection(config)
      case 'sqlite':
        return new SQLiteConnection(config)
      case 'mongodb':
        return new MongoDBConnection(config)
      case 'redis':
        return new RedisConnection(config)
      default:
        throw new Error(`Unsupported database type: ${config.type}`)
    }
  }
}

// Export individual connection classes for direct use
export { PostgreSQLConnection } from './postgres'
export { MySQLConnection } from './mysql'
export { SQLiteConnection } from './sqlite'
export { MongoDBConnection } from './mongo'
export { RedisConnection } from './redis'
