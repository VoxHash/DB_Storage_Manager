import { app } from 'electron'

export class AutoStartupManager {
  private static instance: AutoStartupManager
  private isEnabled: boolean = false

  private constructor() {}

  static getInstance(): AutoStartupManager {
    if (!AutoStartupManager.instance) {
      AutoStartupManager.instance = new AutoStartupManager()
    }
    return AutoStartupManager.instance
  }

  async enable(): Promise<boolean> {
    try {
      // For Windows, we'll use the registry to set auto-startup
      if (process.platform === 'win32') {
        const { exec } = require('child_process')
        const { promisify } = require('util')
        const execAsync = promisify(exec)
        
        const appPath = process.execPath
        const appName = 'DB Storage Manager'
        
        // Create registry entry for auto-startup
        const regCommand = `reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v "${appName}" /t REG_SZ /d "${appPath}" /f`
        
        await execAsync(regCommand)
        this.isEnabled = true
        return true
      }
      
      // For macOS, we'll use LaunchAgents
      if (process.platform === 'darwin') {
        const fs = require('fs')
        const path = require('path')
        const os = require('os')
        
        const plistPath = path.join(os.homedir(), 'Library', 'LaunchAgents', 'com.dbsm.auto-start.plist')
        const plistContent = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.dbsm.auto-start</string>
    <key>ProgramArguments</key>
    <array>
        <string>${process.execPath}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>`
        
        fs.writeFileSync(plistPath, plistContent)
        this.isEnabled = true
        return true
      }
      
      // For Linux, we'll use autostart directory
      if (process.platform === 'linux') {
        const fs = require('fs')
        const path = require('path')
        const os = require('os')
        
        const autostartDir = path.join(os.homedir(), '.config', 'autostart')
        const desktopFile = path.join(autostartDir, 'db-storage-manager.desktop')
        
        // Ensure autostart directory exists
        if (!fs.existsSync(autostartDir)) {
          fs.mkdirSync(autostartDir, { recursive: true })
        }
        
        const desktopContent = `[Desktop Entry]
Type=Application
Name=DB Storage Manager
Comment=Database Storage Management Tool
Exec=${process.execPath}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true`
        
        fs.writeFileSync(desktopFile, desktopContent)
        this.isEnabled = true
        return true
      }
      
      return false
    } catch (error) {
      console.error('Failed to enable auto-startup:', error)
      return false
    }
  }

  async disable(): Promise<boolean> {
    try {
      if (process.platform === 'win32') {
        const { exec } = require('child_process')
        const { promisify } = require('util')
        const execAsync = promisify(exec)
        
        const appName = 'DB Storage Manager'
        const regCommand = `reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v "${appName}" /f`
        
        try {
          await execAsync(regCommand)
        } catch (error) {
          // Registry key might not exist, which is fine
        }
        
        this.isEnabled = false
        return true
      }
      
      if (process.platform === 'darwin') {
        const fs = require('fs')
        const path = require('path')
        const os = require('os')
        
        const plistPath = path.join(os.homedir(), 'Library', 'LaunchAgents', 'com.dbsm.auto-start.plist')
        
        if (fs.existsSync(plistPath)) {
          fs.unlinkSync(plistPath)
        }
        
        this.isEnabled = false
        return true
      }
      
      if (process.platform === 'linux') {
        const fs = require('fs')
        const path = require('path')
        const os = require('os')
        
        const desktopFile = path.join(os.homedir(), '.config', 'autostart', 'db-storage-manager.desktop')
        
        if (fs.existsSync(desktopFile)) {
          fs.unlinkSync(desktopFile)
        }
        
        this.isEnabled = false
        return true
      }
      
      return false
    } catch (error) {
      console.error('Failed to disable auto-startup:', error)
      return false
    }
  }

  async isAutoStartupEnabled(): Promise<boolean> {
    try {
      if (process.platform === 'win32') {
        const { exec } = require('child_process')
        const { promisify } = require('util')
        const execAsync = promisify(exec)
        
        const appName = 'DB Storage Manager'
        const regCommand = `reg query "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v "${appName}"`
        
        try {
          await execAsync(regCommand)
          this.isEnabled = true
          return true
        } catch (error) {
          this.isEnabled = false
          return false
        }
      }
      
      if (process.platform === 'darwin') {
        const fs = require('fs')
        const path = require('path')
        const os = require('os')
        
        const plistPath = path.join(os.homedir(), 'Library', 'LaunchAgents', 'com.dbsm.auto-start.plist')
        const exists = fs.existsSync(plistPath)
        this.isEnabled = exists
        return exists
      }
      
      if (process.platform === 'linux') {
        const fs = require('fs')
        const path = require('path')
        const os = require('os')
        
        const desktopFile = path.join(os.homedir(), '.config', 'autostart', 'db-storage-manager.desktop')
        const exists = fs.existsSync(desktopFile)
        this.isEnabled = exists
        return exists
      }
      
      return false
    } catch (error) {
      console.error('Failed to check auto-startup status:', error)
      return false
    }
  }

  getStatus(): boolean {
    return this.isEnabled
  }
}
