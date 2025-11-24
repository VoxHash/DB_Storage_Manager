import { MongoClient, Db } from 'mongodb'
import { DatabaseConnection, ConnectionConfig, StorageAnalysis, QueryResult, SchemaInfo } from './index'
import { writeFileSync } from 'fs'

export class MongoDBConnection extends DatabaseConnection {
  private client?: MongoClient
  private db?: Db

  async connect(): Promise<void> {
    const connectionString = this.config.connectionString || 
      `mongodb://${this.config.username ? `${this.config.username}:${this.config.password}@` : ''}${this.config.host}:${this.config.port || 27017}/${this.config.database || ''}`

    this.client = new MongoClient(connectionString)
    await this.client.connect()
    
    this.db = this.client.db(this.config.database)
    this.connected = true
  }

  async disconnect(): Promise<void> {
    if (this.client) {
      await this.client.close()
      this.client = undefined
      this.db = undefined
      this.connected = false
    }
  }

  async testConnection(): Promise<void> {
    if (!this.client) {
      await this.connect()
    }
    
    await this.db!.admin().ping()
  }

  async analyzeStorage(): Promise<StorageAnalysis> {
    if (!this.client) {
      await this.connect()
    }

    const db = this.db!

    // Get database stats
    const dbStats = await db.stats()
    const totalSize = dbStats.dataSize + dbStats.indexSize

    // Get collections
    const collections = await db.listCollections().toArray()
    const tables = []

    for (const collection of collections) {
      const collectionName = collection.name
      const coll = db.collection(collectionName)
      
      // Get collection stats
      const collStats = await db.command({ collStats: collectionName })
      const rowCount = collStats.count || 0
      const size = collStats.size || 0
      const indexSize = collStats.totalIndexSize || 0

      tables.push({
        name: collectionName,
        size,
        rowCount,
        indexSize,
        bloat: 0 // MongoDB doesn't have traditional bloat
      })
    }

    // Sort by size descending
    tables.sort((a, b) => b.size - a.size)

    // Get indexes
    const indexes = []
    for (const collection of collections) {
      const collectionName = collection.name
      const coll = db.collection(collectionName)
      const indexList = await coll.indexes()
      
      for (const index of indexList) {
        // Get index size (approximate)
        const indexStats = await db.command({ collStats: collectionName })
        const avgIndexSize = indexStats.totalIndexSize / indexList.length

        indexes.push({
          name: index.name,
          tableName: collectionName,
          size: avgIndexSize,
          bloat: 0
        })
      }
    }

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

    const db = this.db!
    const startTime = Date.now()

    try {
      // Parse MongoDB query (simplified - in real implementation, you'd want a proper parser)
      const queryObj = JSON.parse(query)
      const { collection, operation, filter, projection, sort, limit } = queryObj

      if (!collection || !operation) {
        throw new Error('Query must specify collection and operation')
      }

      const coll = db.collection(collection)
      let result: any[] = []

      switch (operation.toLowerCase()) {
        case 'find':
          const cursor = coll.find(filter || {}, { projection })
          if (sort) cursor.sort(sort)
          if (limit) cursor.limit(limit)
          result = await cursor.toArray()
          break
        case 'aggregate':
          result = await coll.aggregate(queryObj.pipeline || []).toArray()
          break
        case 'count':
          result = [{ count: await coll.countDocuments(filter || {}) }]
          break
        default:
          throw new Error(`Unsupported operation: ${operation}`)
      }

      const executionTime = Date.now() - startTime

      // Get column names from the first document
      const columns = result.length > 0 ? Object.keys(result[0]) : []

      return {
        columns,
        rows: result,
        rowCount: result.length,
        executionTime,
        explainPlan: undefined // MongoDB explain is more complex
      }
    } catch (error) {
      throw new Error(`Query execution failed: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  }

  async getSchema(): Promise<SchemaInfo> {
    if (!this.client) {
      await this.connect()
    }

    const db = this.db!

    // Get collections
    const collections = await db.listCollections().toArray()
    const tables = []

    for (const collection of collections) {
      const collectionName = collection.name
      const coll = db.collection(collectionName)

      // Get sample document to infer schema
      const sampleDoc = await coll.findOne({})
      const columns = sampleDoc ? Object.keys(sampleDoc).map(key => ({
        name: key,
        type: typeof sampleDoc[key],
        nullable: true, // MongoDB fields are always nullable
        defaultValue: undefined
      })) : []

      // Get indexes
      const indexList = await coll.indexes()
      const indexes = indexList.map(index => ({
        name: index.name,
        columns: Object.keys(index.key),
        unique: index.unique || false
      }))

      tables.push({
        name: collectionName,
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
    if (!this.client) {
      await this.connect()
    }

    const db = this.db!

    try {
      // Get all collections and their data
      const collections = await db.listCollections().toArray()
      const backupData: any = {
        database: this.config.database,
        collections: {}
      }

      for (const collection of collections) {
        const collectionName = collection.name
        const coll = db.collection(collectionName)
        const data = await coll.find({}).toArray()
        backupData.collections[collectionName] = data
      }

      // Write backup to file
      const backupJson = JSON.stringify(backupData, null, 2)
      writeFileSync(backupPath, backupJson)

      const stats = require('fs').statSync(backupPath)
      return { path: backupPath, size: stats.size }
    } catch (error) {
      throw new Error(`Failed to create MongoDB backup: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  }

  async restoreBackup(backupPath: string): Promise<void> {
    if (!this.client) {
      await this.connect()
    }

    const db = this.db!

    try {
      // Read backup file
      const backupData = JSON.parse(require('fs').readFileSync(backupPath, 'utf8'))

      // Clear existing collections
      const collections = await db.listCollections().toArray()
      for (const collection of collections) {
        await db.collection(collection.name).drop()
      }

      // Restore collections
      for (const [collectionName, data] of Object.entries(backupData.collections)) {
        if (Array.isArray(data) && data.length > 0) {
          await db.collection(collectionName).insertMany(data as any[])
        }
      }
    } catch (error) {
      throw new Error(`Failed to restore MongoDB backup: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  }
}
