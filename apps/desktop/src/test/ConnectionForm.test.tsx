import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { ConnectionForm } from '@/components/ConnectionForm'

// Mock the electron API
const mockElectronAPI = {
  showOpenDialog: vi.fn().mockResolvedValue({ canceled: false, filePaths: ['/test/db.sqlite'] })
}

// Mock window.electronAPI
Object.defineProperty(window, 'electronAPI', {
  value: mockElectronAPI,
  writable: true
})

describe('ConnectionForm', () => {
  const mockOnSave = vi.fn()
  const mockOnCancel = vi.fn()
  const mockOnTest = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders form fields correctly', () => {
    render(
      <ConnectionForm
        onSave={mockOnSave}
        onCancel={mockOnCancel}
        onTest={mockOnTest}
      />
    )

    expect(screen.getByLabelText('Connection Name')).toBeInTheDocument()
    expect(screen.getByLabelText('Database Type')).toBeInTheDocument()
    expect(screen.getByLabelText('Host')).toBeInTheDocument()
    expect(screen.getByLabelText('Port')).toBeInTheDocument()
    expect(screen.getByLabelText('Database Name')).toBeInTheDocument()
    expect(screen.getByLabelText('Username')).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toBeInTheDocument()
  })

  it('shows SQLite file picker when SQLite is selected', async () => {
    render(
      <ConnectionForm
        onSave={mockOnSave}
        onCancel={mockOnCancel}
        onTest={mockOnTest}
      />
    )

    // Select SQLite
    const typeSelect = screen.getByLabelText('Database Type')
    fireEvent.click(typeSelect)
    
    const sqliteOption = screen.getByText('SQLite')
    fireEvent.click(sqliteOption)

    // Should show file picker
    expect(screen.getByLabelText('Database File')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /folder/i })).toBeInTheDocument()
  })

  it('calls onSave with correct data when form is submitted', async () => {
    render(
      <ConnectionForm
        onSave={mockOnSave}
        onCancel={mockOnCancel}
        onTest={mockOnTest}
      />
    )

    // Fill in form
    fireEvent.change(screen.getByLabelText('Connection Name'), {
      target: { value: 'Test Connection' }
    })
    fireEvent.change(screen.getByLabelText('Host'), {
      target: { value: 'localhost' }
    })
    fireEvent.change(screen.getByLabelText('Port'), {
      target: { value: '5432' }
    })
    fireEvent.change(screen.getByLabelText('Database Name'), {
      target: { value: 'testdb' }
    })
    fireEvent.change(screen.getByLabelText('Username'), {
      target: { value: 'testuser' }
    })
    fireEvent.change(screen.getByLabelText('Password'), {
      target: { value: 'testpass' }
    })

    // Submit form
    fireEvent.click(screen.getByRole('button', { name: /save connection/i }))

    await waitFor(() => {
      expect(mockOnSave).toHaveBeenCalledWith(
        expect.objectContaining({
          name: 'Test Connection',
          type: 'postgresql',
          host: 'localhost',
          port: 5432,
          database: 'testdb',
          username: 'testuser',
          password: 'testpass'
        })
      )
    })
  })

  it('calls onTest when test button is clicked', async () => {
    mockOnTest.mockResolvedValue({ success: true })

    render(
      <ConnectionForm
        onSave={mockOnSave}
        onCancel={mockOnCancel}
        onTest={mockOnTest}
      />
    )

    // Fill in required fields
    fireEvent.change(screen.getByLabelText('Connection Name'), {
      target: { value: 'Test Connection' }
    })

    // Click test button
    fireEvent.click(screen.getByRole('button', { name: /test connection/i }))

    await waitFor(() => {
      expect(mockOnTest).toHaveBeenCalled()
    })
  })

  it('shows test result when test completes', async () => {
    mockOnTest.mockResolvedValue({ success: false, error: 'Connection failed' })

    render(
      <ConnectionForm
        onSave={mockOnSave}
        onCancel={mockOnCancel}
        onTest={mockOnTest}
      />
    )

    // Fill in required fields
    fireEvent.change(screen.getByLabelText('Connection Name'), {
      target: { value: 'Test Connection' }
    })

    // Click test button
    fireEvent.click(screen.getByRole('button', { name: /test connection/i }))

    await waitFor(() => {
      expect(screen.getByText('Connection failed')).toBeInTheDocument()
    })
  })

  it('disables save button when name is empty', () => {
    render(
      <ConnectionForm
        onSave={mockOnSave}
        onCancel={mockOnCancel}
        onTest={mockOnTest}
      />
    )

    const saveButton = screen.getByRole('button', { name: /save connection/i })
    expect(saveButton).toBeDisabled()
  })

  it('calls onCancel when cancel button is clicked', () => {
    render(
      <ConnectionForm
        onSave={mockOnSave}
        onCancel={mockOnCancel}
        onTest={mockOnTest}
      />
    )

    fireEvent.click(screen.getByRole('button', { name: /cancel/i }))
    expect(mockOnCancel).toHaveBeenCalled()
  })
})
