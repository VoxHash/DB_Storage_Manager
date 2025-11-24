import { app } from 'electron'
import { readFile, writeFile, mkdir } from 'fs/promises'
import { join } from 'path'
import * as sodium from 'libsodium-wrappers'

export interface EncryptedStore {
  getSettings(): Promise<Record<string, any>>
  setSettings(settings: Record<string, any>): Promise<void>
  getConnections(): Promise<any[]>
  saveConnections(connections: any[]): Promise<void>
  getSSHKeys(): Promise<any[]>
  saveSSHKeys(keys: any[]): Promise<void>
}

export class SecureStore implements EncryptedStore {
  private userDataPath: string
  private masterKey: Uint8Array | null = null

  constructor() {
    this.userDataPath = app.getPath('userData')
  }

  private async getMasterKey(): Promise<Uint8Array> {
    if (this.masterKey) {
      return this.masterKey
    }

    await sodium.ready()
    
    // Try to load existing master key
    const keyPath = join(this.userDataPath, '.master-key')
    try {
      const keyData = await readFile(keyPath)
      this.masterKey = new Uint8Array(keyData)
      return this.masterKey
    } catch (error) {
      // Generate new master key
      this.masterKey = sodium.crypto_secretbox_keygen()
      await writeFile(keyPath, this.masterKey)
      return this.masterKey
    }
  }

  private async encrypt(data: any): Promise<string> {
    await sodium.ready()
    const masterKey = await this.getMasterKey()
    const plaintext = JSON.stringify(data)
    const nonce = sodium.crypto_secretbox_noncegen()
    const ciphertext = sodium.crypto_secretbox_easy(plaintext, nonce, masterKey)
    
    // Combine nonce and ciphertext
    const combined = new Uint8Array(nonce.length + ciphertext.length)
    combined.set(nonce)
    combined.set(ciphertext, nonce.length)
    
    return sodium.to_base64(combined)
  }

  private async decrypt(encryptedData: string): Promise<any> {
    await sodium.ready()
    const masterKey = await this.getMasterKey()
    const combined = sodium.from_base64(encryptedData)
    
    // Split nonce and ciphertext
    const nonce = combined.slice(0, sodium.crypto_secretbox_NONCEBYTES)
    const ciphertext = combined.slice(sodium.crypto_secretbox_NONCEBYTES)
    
    const plaintext = sodium.crypto_secretbox_open_easy(ciphertext, nonce, masterKey)
    return JSON.parse(sodium.to_string(plaintext))
  }

  private async ensureDirectory(): Promise<void> {
    try {
      await mkdir(this.userDataPath, { recursive: true })
    } catch (error) {
      // Directory might already exist
    }
  }

  async getSettings(): Promise<Record<string, any>> {
    try {
      await this.ensureDirectory()
      const settingsPath = join(this.userDataPath, 'settings.enc')
      const encryptedData = await readFile(settingsPath, 'utf8')
      return await this.decrypt(encryptedData)
    } catch (error) {
      // Return default settings if file doesn't exist
      return {
        theme: 'system',
        language: 'en',
        safeMode: true,
        autoConnect: false,
        notifications: true,
        telemetry: false
      }
    }
  }

  async setSettings(settings: Record<string, any>): Promise<void> {
    try {
      await this.ensureDirectory()
      const settingsPath = join(this.userDataPath, 'settings.enc')
      const encryptedData = await this.encrypt(settings)
      await writeFile(settingsPath, encryptedData)
    } catch (error) {
      throw new Error(`Failed to save settings: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  }

  async getConnections(): Promise<any[]> {
    try {
      await this.ensureDirectory()
      const connectionsPath = join(this.userDataPath, 'connections.enc')
      const encryptedData = await readFile(connectionsPath, 'utf8')
      return await this.decrypt(encryptedData)
    } catch (error) {
      // Return empty array if file doesn't exist
      return []
    }
  }

  async saveConnections(connections: any[]): Promise<void> {
    try {
      await this.ensureDirectory()
      const connectionsPath = join(this.userDataPath, 'connections.enc')
      const encryptedData = await this.encrypt(connections)
      await writeFile(connectionsPath, encryptedData)
    } catch (error) {
      throw new Error(`Failed to save connections: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  }

  async getSSHKeys(): Promise<any[]> {
    try {
      await this.ensureDirectory()
      const sshKeysPath = join(this.userDataPath, 'ssh-keys.enc')
      const encryptedData = await readFile(sshKeysPath, 'utf8')
      return await this.decrypt(encryptedData)
    } catch (error) {
      return []
    }
  }

  async saveSSHKeys(keys: any[]): Promise<void> {
    try {
      await this.ensureDirectory()
      const sshKeysPath = join(this.userDataPath, 'ssh-keys.enc')
      const encryptedData = await this.encrypt(keys)
      await writeFile(sshKeysPath, encryptedData)
    } catch (error) {
      throw new Error(`Failed to save SSH keys: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  }
}
