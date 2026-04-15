import React, { useState } from 'react'
import { useApp } from './context/AppContext'
import Header from './components/Header'
import DateSidebar from './components/DateSidebar'
import MainChart from './components/MainChart'
import JournalPanel from './components/JournalPanel'
import AnalysisPanel from './components/AnalysisPanel'
import LiveDashboard from './components/LiveDashboard'
import KBBrowser from './components/KBBrowser'
import LearnerPanel from './components/LearnerPanel'
import TimeMachineView from './components/TimeMachineView'

const MODES = [
  { id: 'backtest', label: 'Backtest', icon: '◈' },
  { id: 'live', label: 'Live', icon: '◉' },
  { id: 'kb', label: 'Knowledge Base', icon: '◎' },
  { id: 'learner', label: 'Learner', icon: '◇' },
  { id: 'timemachine', label: 'Time Machine', icon: '⟳' },
]

export default function App() {
  const { loading, error } = useApp()
  const [mode, setMode] = useState('backtest')

  return (
    <div className="h-screen bg-gray-950 text-gray-100 flex flex-col overflow-hidden">
      <Header />

      {/* Mode navigation bar */}
      <nav className="flex items-center gap-1 px-4 py-1.5 bg-gray-900/70 border-b border-gray-800/60 z-10">
        {MODES.map(m => (
          <button
            key={m.id}
            onClick={() => setMode(m.id)}
            className={`flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-medium transition-all duration-150 ${
              mode === m.id
                ? 'bg-blue-600/30 text-blue-300 border border-blue-500/40'
                : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/50 border border-transparent'
            }`}
          >
            <span className="text-[10px] opacity-70">{m.icon}</span>
            {m.label}
          </button>
        ))}
        {mode === 'live' && (
          <span className="ml-auto flex items-center gap-1.5 text-[10px] text-emerald-400">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            LIVE
          </span>
        )}
      </nav>

      {/* Mode content */}
      {mode === 'backtest' ? (
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
      ) : mode === 'live' ? (
        <LiveDashboard />
      ) : mode === 'kb' ? (
        <KBBrowser />
      ) : mode === 'learner' ? (
        <LearnerPanel />
      ) : (
        <TimeMachineView />
      )}
    </div>
  )
}
