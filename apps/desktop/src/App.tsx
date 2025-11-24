import React, { useState } from 'react'
import { BrowserRouter as Router } from 'react-router-dom'
import Header from './components/Header'
import Sidebar from './components/Sidebar'
import Dashboard from './routes/Dashboard'
import Settings from './routes/Settings'
import { useI18n } from '@/lib/i18n/useI18n'
import './styles/index.css'

function App() {
  const { t } = useI18n()
  const [currentPage, setCurrentPage] = useState('dashboard')

  const handleSettingsClick = () => {
    setCurrentPage('settings')
  }

  const handlePageChange = (page: string) => {
    setCurrentPage(page)
  }

  const renderPage = () => {
    switch (currentPage) {
      case 'dashboard':
        return <Dashboard />
      case 'settings':
        return <Settings />
      case 'connections':
        return <div className="p-6"><h1 className="text-2xl font-bold">{t('connections')}</h1><p>Connections page coming soon...</p></div>
      case 'analytics':
        return <div className="p-6"><h1 className="text-2xl font-bold">{t('analytics')}</h1><p>Analytics page coming soon...</p></div>
      case 'storage':
        return <div className="p-6"><h1 className="text-2xl font-bold">{t('storage')}</h1><p>Storage page coming soon...</p></div>
      case 'query':
        return <div className="p-6"><h1 className="text-2xl font-bold">{t('queryConsole')}</h1><p>Query console coming soon...</p></div>
      case 'backup':
        return <div className="p-6"><h1 className="text-2xl font-bold">{t('backupRestore')}</h1><p>Backup & restore coming soon...</p></div>
      default:
        return <Dashboard />
    }
  }

  return (
    <Router>
      <div className="min-h-screen bg-background flex">
        <Sidebar currentPage={currentPage} onPageChange={handlePageChange} />
        
        <div className="flex-1 flex flex-col">
          <Header onSettingsClick={handleSettingsClick} />
          
          <main className="flex-1 overflow-auto">
            {renderPage()}
          </main>
        </div>
      </div>
    </Router>
  )
}

export default App