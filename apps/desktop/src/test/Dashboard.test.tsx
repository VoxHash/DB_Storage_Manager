import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Dashboard } from '@/routes/Dashboard'

// Mock the electron API
const mockElectronAPI = {
  analyzeDatabase: vi.fn(),
  getConnections: vi.fn()
}

Object.defineProperty(window, 'electronAPI', {
  value: mockElectronAPI,
  writable: true
})

describe('Dashboard', () => {
  const mockConnections = [
    {
      id: '1',
      name: 'Test PostgreSQL',
      type: 'postgresql' as const,
      host: 'localhost',
      port: 5432,
      database: 'testdb',
      username: 'testuser',
      password: 'testpass'
    },
    {
      id: '2',
      name: 'Test MySQL',
      type: 'mysql' as const,
      host: 'localhost',
      port: 3306,
      database: 'testdb',
      username: 'testuser',
      password: 'testpass'
    }
  ]

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders empty state when no connections', () => {
    render(<Dashboard connections={[]} />)
    
    expect(screen.getByText('No Database Connections')).toBeInTheDocument()
    expect(screen.getByText('Add a database connection to start analyzing storage usage and managing your databases.')).toBeInTheDocument()
  })

  it('renders dashboard with connections', () => {
    render(<Dashboard connections={mockConnections} />)
    
    expect(screen.getByText('Storage Dashboard')).toBeInTheDocument()
    expect(screen.getByText('Monitor database storage usage across all connections')).toBeInTheDocument()
    expect(screen.getByText('Test PostgreSQL')).toBeInTheDocument()
    expect(screen.getByText('Test MySQL')).toBeInTheDocument()
  })

  it('shows overview cards', () => {
    render(<Dashboard connections={mockConnections} />)
    
    expect(screen.getByText('Total Storage')).toBeInTheDocument()
    expect(screen.getByText('Total Tables')).toBeInTheDocument()
    expect(screen.getByText('Total Indexes')).toBeInTheDocument()
    expect(screen.getByText('Largest Table')).toBeInTheDocument()
  })

  it('shows action buttons', () => {
    render(<Dashboard connections={mockConnections} />)
    
    expect(screen.getByRole('button', { name: /add connection/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /export report/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /refresh all/i })).toBeInTheDocument()
  })

  it('displays connection details', () => {
    render(<Dashboard connections={mockConnections} />)
    
    // Check that connection names are displayed
    expect(screen.getByText('Test PostgreSQL')).toBeInTheDocument()
    expect(screen.getByText('Test MySQL')).toBeInTheDocument()
    
    // Check that database types are displayed
    expect(screen.getByText('postgresql • testdb')).toBeInTheDocument()
    expect(screen.getByText('mysql • testdb')).toBeInTheDocument()
  })

  it('shows analyze buttons for each connection', () => {
    render(<Dashboard connections={mockConnections} />)
    
    const analyzeButtons = screen.getAllByRole('button', { name: /analyze/i })
    expect(analyzeButtons).toHaveLength(2)
  })
})
