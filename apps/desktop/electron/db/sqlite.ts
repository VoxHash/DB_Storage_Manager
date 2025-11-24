import Database from 'better-sqlite3'
import { DatabaseConnection, ConnectionConfig, StorageAnalysis, QueryResult, SchemaInfo } from './index'
import { copyFileSync, existsSync, statSync } from 'fs'

export class SQLiteConnection extends DatabaseConnection {
  private db?: Database.Database

  async connect(): Promise<void> {
    if (!this.config.filePath || !existsSync(this.config.filePath)) {
      throw new Error('SQLite file path is required and must exist')
    }

    this.db = new Database(this.config.filePath)
    this.connected = true
  }

  async disconnect(): Promise<void> {
    if (this.db) {
      this.db.close()
      this.db = undefined
      this.connected = false
    }
  }

  async testConnection(): Promise<void> {
    if (!this.db) {
      await this.connect()
    }
    
    const result = this.db!.prepare('SELECT 1 as test').get()
    if (!result) {
      throw new Error('Connection test failed')
    }
  }

  async analyzeStorage(): Promise<StorageAnalysis> {
    if (!this.db) {
      await this.connect()
    }

    const db = this.db!

    // Get database file size
    const stats = statSync(this.config.filePath!)
    const totalSize = stats.size

    // Get table information
    const tablesResult = db.prepare(`
      SELECT 
        name,
        (SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' AND tbl_name = t.name) as index_count
      FROM sqlite_master t
      WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
      ORDER BY name
    `).all()

    const tables = []
    let totalTableSize = 0

    for (const tableRow of tablesResult) {
      const tableName = tableRow.name
      
      // Get table size and row count
      const sizeResult = db.prepare(`
        SELECT 
          COUNT(*) as row_count,
          SUM(pgsize) as page_size
        FROM pragma_page_count(),
        pragma_page_size(),
        (SELECT COUNT(*) FROM ${tableName}) as row_count
      `).get()

      const rowCount = sizeResult?.row_count || 0
      const pageSize = sizeResult?.page_size || 0
      const tableSize = pageSize

      totalTableSize += tableSize

      tables.push({
        name: tableName,
        size: tableSize,
        rowCount,
        indexSize: 0, // SQLite doesn't easily provide index size per table
        bloat: 0
      })
    }

    // Get index information
    const indexesResult = db.prepare(`
      SELECT 
        name,
        tbl_name as table_name
      FROM sqlite_master 
      WHERE type = 'index' AND name NOT LIKE 'sqlite_%'
      ORDER BY name
    `).all()

    const indexes = indexesResult.map(row => ({
      name: row.name,
      tableName: row.table_name,
      size: 0, // SQLite doesn't easily provide per-index size
      bloat: 0
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
    if (!this.db) {
      await this.connect()
    }

    const db = this.db!
    const startTime = Date.now()

    try {
      const stmt = db.prepare(query)
      
      if (query.trim().toLowerCase().startsWith('select')) {
        const rows = stmt.all()
        const executionTime = Date.now() - startTime

        // Get column names from the first row
        const columns = rows.length > 0 ? Object.keys(rows[0]) : []

        // Get explain plan for SELECT queries
        let explainPlan
        try {
          const explainResult = db.prepare(`EXPLAIN QUERY PLAN ${query}`).all()
          explainPlan = explainResult
        } catch (error) {
          // Ignore explain errors
        }

        return {
          columns,
          rows,
          rowCount: rows.length,
          executionTime,
          explainPlan
        }
      } else {
        const result = stmt.run()
        const executionTime = Date.now() - startTime

        return {
          columns: [],
          rows: [],
          rowCount: result.changes || 0,
          executionTime,
          explainPlan: undefined
        }
      }
    } catch (error) {
      throw new Error(`Query execution failed: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  }

  async getSchema(): Promise<SchemaInfo> {
    if (!this.db) {
      await this.connect()
    }

    const db = this.db!

    // Get tables
    const tablesResult = db.prepare(`
      SELECT name 
      FROM sqlite_master 
      WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
      ORDER BY name
    `).all()

    const tables = []

    for (const tableRow of tablesResult) {
      const tableName = tableRow.name

      // Get columns using PRAGMA table_info
      const columnsResult = db.prepare(`PRAGMA table_info(${tableName})`).all()

      const columns = columnsResult.map(col => ({
        name: col.name,
        type: col.type,
        nullable: col.notnull === 0,
        defaultValue: col.dflt_value
      }))

      // Get indexes
      const indexesResult = db.prepare(`
        SELECT 
          name,
          sql
        FROM sqlite_master 
        WHERE type = 'index' AND tbl_name = ? AND name NOT LIKE 'sqlite_%'
        ORDER BY name
      `).all(tableName)

      const indexes = indexesResult.map(idx => ({
        name: idx.name,
        columns: [], // Would need to parse SQL to extract columns
        unique: idx.sql?.includes('UNIQUE') || false
      }))

      tables.push({
        name: tableName,
        columns,
        indexes
      })
    }

    return {
      schemas: [{
        name: 'main',
        tables
      }]
    }
  }

  async createBackup(backupPath: string): Promise<{ path: string; size: number }> {
    if (!this.db) {
      await this.connect()
    }

    // For SQLite, we can simply copy the file
    try {
      copyFileSync(this.config.filePath!, backupPath)
      const stats = statSync(backupPath)
      return { path: backupPath, size: stats.size }
    } catch (error) {
      throw new Error(`Failed to create SQLite backup: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  }

  async restoreBackup(backupPath: string): Promise<void> {
    if (!this.db) {
      await this.connect()
    }

    // For SQLite restore, we need to close the current connection first
    if (this.db) {
      this.db.close()
      this.connected = false
    }

    try {
      // Copy the backup file to the original location
      copyFileSync(backupPath, this.config.filePath!)
      
      // Reconnect
      this.db = new Database(this.config.filePath!)
      this.connected = true
    } catch (error) {
      throw new Error(`Failed to restore SQLite backup: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  }
}
