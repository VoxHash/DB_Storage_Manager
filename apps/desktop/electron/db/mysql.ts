import mysql from 'mysql2/promise'
import { DatabaseConnection, ConnectionConfig, StorageAnalysis, QueryResult, SchemaInfo } from './index'
import { writeFileSync, readFileSync } from 'fs'

export class MySQLConnection extends DatabaseConnection {
  private connection?: mysql.Connection

  async connect(): Promise<void> {
    this.connection = await mysql.createConnection({
      host: this.config.host,
      port: this.config.port || 3306,
      database: this.config.database,
      user: this.config.username,
      password: this.config.password,
      connectionString: this.config.connectionString,
    })

    this.connected = true
  }

  async disconnect(): Promise<void> {
    if (this.connection) {
      await this.connection.end()
      this.connection = undefined
      this.connected = false
    }
  }

  async testConnection(): Promise<void> {
    if (!this.connection) {
      await this.connect()
    }
    
    const [rows] = await this.connection!.execute('SELECT 1 as test')
    if (!rows || (rows as any[]).length === 0) {
      throw new Error('Connection test failed')
    }
  }

  async analyzeStorage(): Promise<StorageAnalysis> {
    if (!this.connection) {
      await this.connect()
    }

    const connection = this.connection!

    // Get database size
    const [dbSizeResult] = await connection.execute(`
      SELECT 
        ROUND(SUM(data_length + index_length) / 1024 / 1024, 2) AS size_mb,
        SUM(data_length + index_length) AS size_bytes
      FROM information_schema.tables 
      WHERE table_schema = ?
    `, [this.config.database])

    const totalSize = (dbSizeResult as any[])[0]?.size_bytes || 0

    // Get table information
    const [tablesResult] = await connection.execute(`
      SELECT 
        table_name,
        ROUND((data_length + index_length) / 1024 / 1024, 2) AS size_mb,
        (data_length + index_length) AS size_bytes,
        ROUND(data_length / 1024 / 1024, 2) AS table_size_mb,
        data_length AS table_size_bytes,
        ROUND(index_length / 1024 / 1024, 2) AS index_size_mb,
        index_length AS index_size_bytes,
        table_rows AS row_count
      FROM information_schema.tables 
      WHERE table_schema = ?
      ORDER BY (data_length + index_length) DESC
    `, [this.config.database])

    const tables = (tablesResult as any[]).map(row => ({
      name: row.table_name,
      size: row.size_bytes,
      rowCount: row.row_count || 0,
      indexSize: row.index_size_bytes,
      bloat: 0 // Placeholder for bloat calculation
    }))

    // Get index information
    const [indexesResult] = await connection.execute(`
      SELECT 
        index_name,
        table_name,
        ROUND(stat_value * @@innodb_page_size / 1024 / 1024, 2) AS size_mb,
        stat_value * @@innodb_page_size AS size_bytes
      FROM information_schema.innodb_buffer_stats_by_table 
      WHERE object_schema = ?
      ORDER BY stat_value * @@innodb_page_size DESC
    `, [this.config.database])

    const indexes = (indexesResult as any[]).map(row => ({
      name: row.index_name,
      tableName: row.table_name,
      size: row.size_bytes,
      bloat: 0 // Placeholder for bloat calculation
    }))

    const largestTable = tables.length > 0 ? tables[0] : { name: 'N/A', size: 0, rowCount: 0 }

    return {
      totalSize,
      tableCount: tables.length,
      indexCount: indexes.length,
      largestTable,
      tables,
      indexes,
      lastAnalyzed: new Date().toISOString()
    }
  }

  async executeQuery(query: string): Promise<QueryResult> {
    if (!this.connection) {
      await this.connect()
    }

    const startTime = Date.now()
    const [rows, fields] = await this.connection!.execute(query)
    const executionTime = Date.now() - startTime

    // Get explain plan if it's a SELECT query
    let explainPlan
    if (query.trim().toLowerCase().startsWith('select')) {
      try {
        const [explainResult] = await this.connection!.execute(`EXPLAIN ${query}`)
        explainPlan = explainResult
      } catch (error) {
        // Ignore explain errors
      }
    }

    return {
      columns: fields?.map(field => field.name) || [],
      rows: rows as any[],
      rowCount: (rows as any[]).length,
      executionTime,
      explainPlan
    }
  }

  async getSchema(): Promise<SchemaInfo> {
    if (!this.connection) {
      await this.connect()
    }

    const connection = this.connection!

    // Get tables
    const [tablesResult] = await connection.execute(`
      SELECT table_name 
      FROM information_schema.tables 
      WHERE table_schema = ?
      ORDER BY table_name
    `, [this.config.database])

    const tables = []

    for (const tableRow of tablesResult as any[]) {
      const tableName = tableRow.table_name

      // Get columns
      const [columnsResult] = await connection.execute(`
        SELECT 
          column_name,
          data_type,
          is_nullable,
          column_default
        FROM information_schema.columns 
        WHERE table_schema = ? AND table_name = ?
        ORDER BY ordinal_position
      `, [this.config.database, tableName])

      const columns = (columnsResult as any[]).map(col => ({
        name: col.column_name,
        type: col.data_type,
        nullable: col.is_nullable === 'YES',
        defaultValue: col.column_default
      }))

      // Get indexes
      const [indexesResult] = await connection.execute(`
        SELECT 
          index_name,
          column_name,
          non_unique
        FROM information_schema.statistics 
        WHERE table_schema = ? AND table_name = ?
        ORDER BY index_name, seq_in_index
      `, [this.config.database, tableName])

      const indexMap = new Map()
      for (const idxRow of indexesResult as any[]) {
        const indexName = idxRow.index_name
        if (!indexMap.has(indexName)) {
          indexMap.set(indexName, {
            name: indexName,
            columns: [],
            unique: idxRow.non_unique === 0
          })
        }
        indexMap.get(indexName).columns.push(idxRow.column_name)
      }

      const indexes = Array.from(indexMap.values())

      tables.push({
        name: tableName,
        columns,
        indexes
      })
    }

    return {
      schemas: [{
        name: this.config.database || 'default',
        tables
      }]
    }
  }

  async createBackup(backupPath: string): Promise<{ path: string; size: number }> {
    if (!this.connection) {
      await this.connect()
    }

    // For MySQL, we'll use mysqldump via child_process
    const { spawn } = require('child_process')

    return new Promise((resolve, reject) => {
      const mysqldump = spawn('mysqldump', [
        '--host', this.config.host || 'localhost',
        '--port', (this.config.port || 3306).toString(),
        '--user', this.config.username || '',
        '--password=' + (this.config.password || ''),
        '--single-transaction',
        '--routines',
        '--triggers',
        this.config.database || ''
      ])

      const fs = require('fs')
      const writeStream = fs.createWriteStream(backupPath)

      mysqldump.stdout.pipe(writeStream)

      mysqldump.on('close', async (code: number) => {
        if (code === 0) {
          try {
            const stats = await require('fs').promises.stat(backupPath)
            resolve({ path: backupPath, size: stats.size })
          } catch (error) {
            reject(new Error('Failed to get backup file size'))
          }
        } else {
          reject(new Error(`mysqldump failed with code ${code}`))
        }
      })

      mysqldump.on('error', (error: Error) => {
        reject(new Error(`mysqldump error: ${error.message}`))
      })
    })
  }

  async restoreBackup(backupPath: string): Promise<void> {
    if (!this.connection) {
      await this.connect()
    }

    const { spawn } = require('child_process')

    return new Promise((resolve, reject) => {
      const mysql = spawn('mysql', [
        '--host', this.config.host || 'localhost',
        '--port', (this.config.port || 3306).toString(),
        '--user', this.config.username || '',
        '--password=' + (this.config.password || ''),
        this.config.database || ''
      ])

      const fs = require('fs')
      const readStream = fs.createReadStream(backupPath)
      readStream.pipe(mysql.stdin)

      mysql.on('close', (code: number) => {
        if (code === 0) {
          resolve()
        } else {
          reject(new Error(`mysql restore failed with code ${code}`))
        }
      })

      mysql.on('error', (error: Error) => {
        reject(new Error(`mysql restore error: ${error.message}`))
      })
    })
  }
}
