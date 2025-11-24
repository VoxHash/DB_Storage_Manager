import { Client } from 'pg'
import { DatabaseConnection, ConnectionConfig, StorageAnalysis, QueryResult, SchemaInfo } from './index'
import { copyFileSync, existsSync } from 'fs'
import { join } from 'path'

export class PostgreSQLConnection extends DatabaseConnection {
  private client?: Client

  async connect(): Promise<void> {
    this.client = new Client({
      host: this.config.host,
      port: this.config.port || 5432,
      database: this.config.database,
      user: this.config.username,
      password: this.config.password,
      connectionString: this.config.connectionString,
    })

    await this.client.connect()
    this.connected = true
  }

  async disconnect(): Promise<void> {
    if (this.client) {
      await this.client.end()
      this.client = undefined
      this.connected = false
    }
  }

  async testConnection(): Promise<void> {
    if (!this.client) {
      await this.connect()
    }
    
    const result = await this.client!.query('SELECT 1')
    if (result.rows.length === 0) {
      throw new Error('Connection test failed')
    }
  }

  async analyzeStorage(): Promise<StorageAnalysis> {
    if (!this.client) {
      await this.connect()
    }

    const client = this.client!

    // Get database size
    const dbSizeResult = await client.query(`
      SELECT pg_size_pretty(pg_database_size(current_database())) as size,
             pg_database_size(current_database()) as size_bytes
    `)
    const totalSize = parseInt(dbSizeResult.rows[0].size_bytes)

    // Get table information
    const tablesResult = await client.query(`
      SELECT 
        schemaname,
        tablename,
        pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size,
        pg_total_relation_size(schemaname||'.'||tablename) as size_bytes,
        pg_size_pretty(pg_relation_size(schemaname||'.'||tablename)) as table_size,
        pg_relation_size(schemaname||'.'||tablename) as table_size_bytes,
        n_tup_ins + n_tup_upd + n_tup_del as row_count
      FROM pg_stat_user_tables 
      ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
    `)

    // Get index information
    const indexesResult = await client.query(`
      SELECT 
        schemaname,
        indexname,
        tablename,
        pg_size_pretty(pg_relation_size(schemaname||'.'||indexname)) as size,
        pg_relation_size(schemaname||'.'||indexname) as size_bytes
      FROM pg_stat_user_indexes
      ORDER BY pg_relation_size(schemaname||'.'||indexname) DESC
    `)

    const tables = tablesResult.rows.map(row => ({
      name: `${row.schemaname}.${row.tablename}`,
      size: parseInt(row.size_bytes),
      rowCount: parseInt(row.row_count) || 0,
      indexSize: 0, // Will be calculated separately
      bloat: 0 // Placeholder for bloat calculation
    }))

    const indexes = indexesResult.rows.map(row => ({
      name: `${row.schemaname}.${row.indexname}`,
      tableName: `${row.schemaname}.${row.tablename}`,
      size: parseInt(row.size_bytes),
      bloat: 0 // Placeholder for bloat calculation
    }))

    // Calculate index sizes per table
    tables.forEach(table => {
      const tableIndexes = indexes.filter(idx => idx.tableName === table.name)
      table.indexSize = tableIndexes.reduce((sum, idx) => sum + idx.size, 0)
    })

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
    if (!this.client) {
      await this.connect()
    }

    const startTime = Date.now()
    const result = await this.client!.query(query)
    const executionTime = Date.now() - startTime

    // Get explain plan if it's a SELECT query
    let explainPlan
    if (query.trim().toLowerCase().startsWith('select')) {
      try {
        const explainResult = await this.client!.query(`EXPLAIN (FORMAT JSON) ${query}`)
        explainPlan = explainResult.rows[0]['QUERY PLAN']
      } catch (error) {
        // Ignore explain errors
      }
    }

    return {
      columns: result.fields.map(field => field.name),
      rows: result.rows,
      rowCount: result.rowCount,
      executionTime,
      explainPlan
    }
  }

  async getSchema(): Promise<SchemaInfo> {
    if (!this.client) {
      await this.connect()
    }

    const client = this.client!

    // Get schemas
    const schemasResult = await client.query(`
      SELECT schema_name 
      FROM information_schema.schemata 
      WHERE schema_name NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
      ORDER BY schema_name
    `)

    const schemas = []

    for (const schemaRow of schemasResult.rows) {
      const schemaName = schemaRow.schema_name

      // Get tables in this schema
      const tablesResult = await client.query(`
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = $1 AND table_type = 'BASE TABLE'
        ORDER BY table_name
      `, [schemaName])

      const tables = []

      for (const tableRow of tablesResult.rows) {
        const tableName = tableRow.table_name

        // Get columns
        const columnsResult = await client.query(`
          SELECT 
            column_name,
            data_type,
            is_nullable,
            column_default
          FROM information_schema.columns 
          WHERE table_schema = $1 AND table_name = $2
          ORDER BY ordinal_position
        `, [schemaName, tableName])

        const columns = columnsResult.rows.map(col => ({
          name: col.column_name,
          type: col.data_type,
          nullable: col.is_nullable === 'YES',
          defaultValue: col.column_default
        }))

        // Get indexes
        const indexesResult = await client.query(`
          SELECT 
            indexname,
            indexdef
          FROM pg_indexes 
          WHERE schemaname = $1 AND tablename = $2
        `, [schemaName, tableName])

        const indexes = indexesResult.rows.map(idx => ({
          name: idx.indexname,
          columns: [], // Would need to parse indexdef to extract columns
          unique: idx.indexdef.includes('UNIQUE')
        }))

        tables.push({
          name: tableName,
          columns,
          indexes
        })
      }

      schemas.push({
        name: schemaName,
        tables
      })
    }

    return { schemas }
  }

  async createBackup(backupPath: string): Promise<{ path: string; size: number }> {
    if (!this.client) {
      await this.connect()
    }

    // For PostgreSQL, we'll use pg_dump via child_process
    const { spawn } = require('child_process')
    const { promisify } = require('util')
    const { writeFile } = require('fs').promises

    return new Promise((resolve, reject) => {
      const pgDump = spawn('pg_dump', [
        '--host', this.config.host || 'localhost',
        '--port', (this.config.port || 5432).toString(),
        '--username', this.config.username || '',
        '--dbname', this.config.database || '',
        '--format', 'custom',
        '--file', backupPath
      ])

      if (this.config.password) {
        pgDump.env.PGPASSWORD = this.config.password
      }

      pgDump.on('close', async (code: number) => {
        if (code === 0) {
          try {
            const stats = await require('fs').promises.stat(backupPath)
            resolve({ path: backupPath, size: stats.size })
          } catch (error) {
            reject(new Error('Failed to get backup file size'))
          }
        } else {
          reject(new Error(`pg_dump failed with code ${code}`))
        }
      })

      pgDump.on('error', (error: Error) => {
        reject(new Error(`pg_dump error: ${error.message}`))
      })
    })
  }

  async restoreBackup(backupPath: string): Promise<void> {
    if (!this.client) {
      await this.connect()
    }

    const { spawn } = require('child_process')

    return new Promise((resolve, reject) => {
      const pgRestore = spawn('pg_restore', [
        '--host', this.config.host || 'localhost',
        '--port', (this.config.port || 5432).toString(),
        '--username', this.config.username || '',
        '--dbname', this.config.database || '',
        '--clean',
        '--if-exists',
        backupPath
      ])

      if (this.config.password) {
        pgRestore.env.PGPASSWORD = this.config.password
      }

      pgRestore.on('close', (code: number) => {
        if (code === 0) {
          resolve()
        } else {
          reject(new Error(`pg_restore failed with code ${code}`))
        }
      })

      pgRestore.on('error', (error: Error) => {
        reject(new Error(`pg_restore error: ${error.message}`))
      })
    })
  }
}
