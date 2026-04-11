import React from 'react'
import { useApp } from '../context/AppContext'

export default function Header() {
  const { split, setSplit, runStatus, triggerRun, equity } = useApp()

  const splits = ['train', 'test', 'holdout']
  const metrics = equity?.metrics || {}

  return (
    <header className="flex items-center justify-between px-5 py-2.5 bg-gray-900/90 backdrop-blur-sm border-b border-gray-800 z-20">
      {/* Left: Logo */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-cyan-400 flex items-center justify-center text-sm font-bold text-white shadow-lg shadow-blue-500/20">
            J
          </div>
          <div>
            <h1 className="text-base font-bold tracking-tight text-white">JACK V2</h1>
            <p className="text-[10px] text-gray-500 -mt-0.5 tracking-wider uppercase">Bank Nifty Engine</p>
          </div>
        </div>

        {/* Quick Metrics */}
        {metrics.total_trades > 0 && (
          <div className="hidden md:flex items-center gap-4 ml-6 pl-6 border-l border-gray-700">
            <MetricBadge label="Return" value={`${metrics.total_return_pct?.toFixed(1)}%`} positive={metrics.total_return_pct > 0} />
            <MetricBadge label="Sharpe" value={metrics.sharpe?.toFixed(2)} positive={metrics.sharpe > 1} />
            <MetricBadge label="Win Rate" value={`${metrics.win_rate?.toFixed(1)}%`} positive={metrics.win_rate > 55} />
            <MetricBadge label="Trades" value={metrics.total_trades} />
          </div>
        )}
      </div>

      {/* Center: Split Pills */}
      <div className="flex items-center gap-1 bg-gray-800/60 p-1 rounded-full">
        {splits.map(s => (
          <button
            key={s}
            id={`split-${s}`}
            onClick={() => setSplit(s)}
            className={`split-pill ${split === s ? 'active' : ''}`}
          >
            {s}
          </button>
        ))}
      </div>

      {/* Right: Actions */}
      <div className="flex items-center gap-3">
        <button
          id="run-simulation-btn"
          onClick={triggerRun}
          disabled={runStatus === 'running'}
          className={`flex items-center gap-2 px-4 py-1.5 rounded-lg text-xs font-semibold transition-all duration-200 ${
            runStatus === 'running'
              ? 'bg-gray-700 text-gray-400 cursor-wait'
              : runStatus === 'done'
              ? 'bg-emerald-600 text-white'
              : runStatus === 'error'
              ? 'bg-red-600 text-white'
              : 'bg-emerald-600 hover:bg-emerald-500 text-white shadow-lg shadow-emerald-600/20'
          }`}
        >
          {runStatus === 'running' ? (
            <>
              <span className="spinner" />
              Running...
            </>
          ) : runStatus === 'done' ? (
            <>✓ Done</>
          ) : runStatus === 'error' ? (
            <>✗ Error</>
          ) : (
            <>▶ Run Sim</>
          )}
        </button>
      </div>
    </header>
  )
}

function MetricBadge({ label, value, positive }) {
  return (
    <div className="text-center">
      <div className={`text-xs font-semibold font-mono ${
        positive === undefined ? 'text-gray-300' :
        positive ? 'text-emerald-400' : 'text-red-400'
      }`}>
        {value}
      </div>
      <div className="text-[9px] text-gray-500 uppercase tracking-wider">{label}</div>
    </div>
  )
}
