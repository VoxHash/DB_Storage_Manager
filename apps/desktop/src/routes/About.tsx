import React from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Database, Github, ExternalLink, Heart } from 'lucide-react'

export function About() {
  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="text-center space-y-4">
        <div className="mx-auto w-16 h-16 bg-primary/10 rounded-full flex items-center justify-center">
          <Database className="h-8 w-8 text-primary" />
        </div>
        <div>
          <h1 className="text-3xl font-bold">DB Storage Manager</h1>
          <p className="text-muted-foreground text-lg">
            A production-ready desktop application for visualizing and managing database storage
          </p>
        </div>
      </div>

      {/* Features */}
      <Card>
        <CardHeader>
          <CardTitle>Features</CardTitle>
          <CardDescription>
            Everything you need to manage your database storage
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <h4 className="font-medium">Database Support</h4>
              <p className="text-sm text-muted-foreground">
                PostgreSQL, MySQL/MariaDB, SQLite, MongoDB, and Redis
              </p>
            </div>
            <div className="space-y-2">
              <h4 className="font-medium">Storage Analysis</h4>
              <p className="text-sm text-muted-foreground">
                Comprehensive storage insights and growth tracking
              </p>
            </div>
            <div className="space-y-2">
              <h4 className="font-medium">Query Console</h4>
              <p className="text-sm text-muted-foreground">
                Safe-mode query execution with syntax highlighting
              </p>
            </div>
            <div className="space-y-2">
              <h4 className="font-medium">Backup & Restore</h4>
              <p className="text-sm text-muted-foreground">
                Automated backups with local and cloud storage
              </p>
            </div>
            <div className="space-y-2">
              <h4 className="font-medium">Schema Explorer</h4>
              <p className="text-sm text-muted-foreground">
                Visual database schema browsing and management
              </p>
            </div>
            <div className="space-y-2">
              <h4 className="font-medium">Security</h4>
              <p className="text-sm text-muted-foreground">
                Encrypted credential storage and safe-mode defaults
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Technology Stack */}
      <Card>
        <CardHeader>
          <CardTitle>Technology Stack</CardTitle>
          <CardDescription>
            Built with modern technologies for reliability and performance
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div className="space-y-1">
              <h4 className="font-medium text-blue-600">Frontend</h4>
              <ul className="space-y-1 text-muted-foreground">
                <li>React 18</li>
                <li>TypeScript</li>
                <li>Tailwind CSS</li>
                <li>shadcn/ui</li>
              </ul>
            </div>
            <div className="space-y-1">
              <h4 className="font-medium text-green-600">Desktop</h4>
              <ul className="space-y-1 text-muted-foreground">
                <li>Electron 31</li>
                <li>Vite</li>
                <li>Node.js</li>
              </ul>
            </div>
            <div className="space-y-1">
              <h4 className="font-medium text-orange-600">Database</h4>
              <ul className="space-y-1 text-muted-foreground">
                <li>PostgreSQL</li>
                <li>MySQL/MariaDB</li>
                <li>SQLite</li>
                <li>MongoDB</li>
                <li>Redis</li>
              </ul>
            </div>
            <div className="space-y-1">
              <h4 className="font-medium text-purple-600">Tools</h4>
              <ul className="space-y-1 text-muted-foreground">
                <li>Monaco Editor</li>
                <li>Recharts</li>
                <li>libsodium</li>
                <li>ssh2</li>
              </ul>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Version Info */}
      <Card>
        <CardHeader>
          <CardTitle>Version Information</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <p className="font-medium">Application Version</p>
              <p className="text-muted-foreground">1.0.0</p>
            </div>
            <div>
              <p className="font-medium">Build Type</p>
              <p className="text-muted-foreground">Production</p>
            </div>
            <div>
              <p className="font-medium">Electron Version</p>
              <p className="text-muted-foreground">31.0.0</p>
            </div>
            <div>
              <p className="font-medium">Node.js Version</p>
              <p className="text-muted-foreground">18.0.0+</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Links */}
      <Card>
        <CardHeader>
          <CardTitle>Links & Resources</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <Github className="h-4 w-4" />
              <span>GitHub Repository</span>
            </div>
            <Button variant="outline" size="sm">
              <ExternalLink className="h-4 w-4 mr-2" />
              Open
            </Button>
          </div>
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <ExternalLink className="h-4 w-4" />
              <span>Documentation</span>
            </div>
            <Button variant="outline" size="sm">
              <ExternalLink className="h-4 w-4 mr-2" />
              Open
            </Button>
          </div>
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <Heart className="h-4 w-4" />
              <span>Report Issues</span>
            </div>
            <Button variant="outline" size="sm">
              <ExternalLink className="h-4 w-4 mr-2" />
              Open
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* License */}
      <Card>
        <CardHeader>
          <CardTitle>License</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            This software is licensed under the MIT License. See the LICENSE file for details.
          </p>
        </CardContent>
      </Card>

      {/* Footer */}
      <div className="text-center text-sm text-muted-foreground pt-8">
        <p>Made with <Heart className="inline h-3 w-3 text-red-500" /> for developers</p>
        <p className="mt-2">© 2024 DB Storage Manager. All rights reserved.</p>
      </div>
    </div>
  )
}
