import React from 'react'
import { useApp } from './context/AppContext'
import Header from './components/Header'
import DateSidebar from './components/DateSidebar'
import MainChart from './components/MainChart'
import JournalPanel from './components/JournalPanel'
import AnalysisPanel from './components/AnalysisPanel'

export default function App() {
  const { loading, error } = useApp()

  return (
    <div className="h-screen bg-gray-950 text-gray-100 flex flex-col overflow-hidden">
      <Header />
      <div className="flex flex-1 overflow-hidden">
        <DateSidebar />
        <main className="flex-1 flex flex-col overflow-hidden p-3 gap-3">
          {error ? (
            <div className="flex-1 flex items-center justify-center">
              <div className="glass-panel p-8 text-center max-w-md animate-fade-in">
                <div className="text-4xl mb-4">⚠️</div>
                <h2 className="text-lg font-semibold text-gray-200 mb-2">Connection Error</h2>
                <p className="text-sm text-gray-400 mb-4">{error}</p>
                <p className="text-xs text-gray-500">
                  Make sure the backend is running on port 8000.<br />
                  <code className="text-gray-400 bg-gray-900 px-2 py-1 rounded mt-2 inline-block">
                    uvicorn jack.api.main:app --reload --port 8000
                  </code>
                </p>
              </div>
            </div>
          ) : (
            <>
              <div className="flex-1 min-h-0">
                <MainChart />
              </div>
              <div className="flex gap-3" style={{ height: '280px' }}>
                <JournalPanel />
                <AnalysisPanel />
              </div>
            </>
          )}
        </main>
      </div>
    </div>
  )
}
