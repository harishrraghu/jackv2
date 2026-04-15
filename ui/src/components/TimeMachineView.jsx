import React, { useState } from 'react'
import { runTimeMachine, simulateDay } from '../api/client'

function StatCard({ label, value, valueClass = 'text-gray-100', sub }) {
  return (
    <div className="glass-panel p-3 text-center">
      <div className="text-base font-bold font-mono leading-none mb-1">
        <span className={valueClass}>{value ?? '—'}</span>
      </div>
      <div className="text-[9px] text-gray-600 uppercase tracking-wider">{label}</div>
      {sub && <div className="text-[9px] text-gray-500 mt-0.5">{sub}</div>}
    </div>
  )
}

const fmt = (n, d = 2) => n == null ? '—' : Number(n).toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d })

export default function TimeMachineView() {
  const today = new Date().toISOString().slice(0, 10)
  const thirtyAgo = new Date(Date.now() - 30 * 864e5).toISOString().slice(0, 10)

  const [mode, setMode] = useState('range') // 'range' or 'single'
  const [startDate, setStartDate] = useState(thirtyAgo)
  const [endDate, setEndDate] = useState(today)
  const [singleDate, setSingleDate] = useState('2021-06-21')
  const [freezeKB, setFreezeKB] = useState(false)
  const [running, setRunning] = useState(false)
  const [results, setResults] = useState(null)
  const [agentMessages, setAgentMessages] = useState(null)
  const [err, setErr] = useState(null)

  const handleRunRange = async () => {
    if (!startDate || !endDate) return
    setErr(null); setResults(null); setAgentMessages(null); setRunning(true)
    try {
      const data = await runTimeMachine({ start_date: startDate, end_date: endDate, kb_freeze_date: freezeKB ? startDate : null })
      if (data.status === 'ok') {
        setResults(data.results)
      } else {
        setErr(data.reason || 'Unknown error')
      }
    } catch (e) {
      setErr(e.message)
    }
    setRunning(false)
  }

  const handleRunSingle = async () => {
    if (!singleDate) return
    setErr(null); setResults(null); setAgentMessages(null); setRunning(true)
    try {
      const data = await simulateDay({ date: singleDate, kb_freeze: freezeKB })
      if (data.status === 'ok') {
        setResults(data.results)
        setAgentMessages(data.agent_messages)
      } else {
        setErr(data.reason || 'Unknown error')
      }
    } catch (e) {
      setErr(e.message)
    }
    setRunning(false)
  }

  const summary = results?.summary || {}
  const dailyResults = results?.daily_results || []
  const strategyBreakdown = summary.strategy_breakdown || {}

  return (
    <div className="flex-1 overflow-auto p-4 space-y-3">
      {/* Mode Tabs */}
      <div className="flex gap-2 mb-2">
        <button onClick={() => setMode('range')}
          className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${mode === 'range' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-gray-200'}`}>
          Date Range Backtest
        </button>
        <button onClick={() => setMode('single')}
          className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${mode === 'single' ? 'bg-purple-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-gray-200'}`}>
          Single Day (All Agents)
        </button>
      </div>

      {/* Controls */}
      <div className="glass-panel p-4 flex items-end gap-4 flex-wrap">
        {mode === 'range' ? (
          <>
            <div className="flex flex-col gap-1">
              <label className="text-[10px] text-gray-500 uppercase tracking-wider">Start Date</label>
              <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)} disabled={running}
                className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-gray-200 focus:outline-none focus:border-blue-500 disabled:opacity-40" />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[10px] text-gray-500 uppercase tracking-wider">End Date</label>
              <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)} disabled={running}
                className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-gray-200 focus:outline-none focus:border-blue-500 disabled:opacity-40" />
            </div>
          </>
        ) : (
          <div className="flex flex-col gap-1">
            <label className="text-[10px] text-gray-500 uppercase tracking-wider">Trading Date</label>
            <input type="date" value={singleDate} onChange={e => setSingleDate(e.target.value)} disabled={running}
              className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-gray-200 focus:outline-none focus:border-purple-500 disabled:opacity-40" />
          </div>
        )}

        <label className="flex items-center gap-2 cursor-pointer pb-1.5">
          <div onClick={() => !running && setFreezeKB(v => !v)}
            className={`w-8 h-4 rounded-full transition-colors relative ${freezeKB ? 'bg-blue-600' : 'bg-gray-700'} ${running ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}>
            <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-transform ${freezeKB ? 'translate-x-4' : 'translate-x-0.5'}`} />
          </div>
          <span className="text-[10px] text-gray-400">Freeze KB</span>
        </label>

        <button
          onClick={mode === 'range' ? handleRunRange : handleRunSingle}
          disabled={running}
          className={`ml-auto px-5 py-2 rounded-lg text-xs font-bold transition-all flex items-center gap-2 ${
            running ? 'bg-gray-700 text-gray-400 cursor-wait'
              : mode === 'range' ? 'bg-blue-600 hover:bg-blue-500 text-white shadow-lg shadow-blue-600/20'
              : 'bg-purple-600 hover:bg-purple-500 text-white shadow-lg shadow-purple-600/20'
          }`}>
          {running ? (
            <><span className="w-3 h-3 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" /> Running...</>
          ) : mode === 'range' ? 'Run Replay' : 'Simulate Day'}
        </button>
      </div>

      {err && <div className="glass-panel p-3 border border-red-700/40 text-xs text-red-400">{err}</div>}

      {/* Agent Messages (single day mode) */}
      {agentMessages && (
        <div className="glass-panel p-3">
          <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-2">Agent Communication</div>
          <div className="space-y-1">
            {Object.entries(agentMessages).map(([key, msg]) => (
              <div key={key} className="text-xs text-gray-400 flex gap-2">
                <span className="text-purple-400 font-mono">{key.replace(/_/g, ' ')}</span>
                <span className="text-gray-600">|</span>
                <span>{msg}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Results */}
      {results && (
        <>
          <div className="grid grid-cols-5 gap-3">
            <StatCard label="Trading Days" value={summary.trading_days ?? '—'} />
            <StatCard label="Total Trades" value={summary.total_trades ?? '—'} />
            <StatCard label="Win Rate"
              value={summary.win_rate != null ? `${summary.win_rate}%` : '—'}
              valueClass={summary.win_rate >= 50 ? 'text-emerald-400' : 'text-red-400'} />
            <StatCard label="Net P&L"
              value={summary.total_pnl != null ? `${fmt(summary.total_pnl, 0)}` : '—'}
              valueClass={summary.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'} />
            <StatCard label="Sharpe"
              value={summary.sharpe_ratio != null ? fmt(summary.sharpe_ratio) : '—'}
              valueClass={summary.sharpe_ratio >= 1 ? 'text-emerald-400' : summary.sharpe_ratio >= 0 ? 'text-amber-400' : 'text-red-400'} />
          </div>

          <div className="grid grid-cols-4 gap-3">
            <StatCard label="Profit Factor" value={summary.profit_factor != null ? fmt(summary.profit_factor) : '—'} />
            <StatCard label="Max DD" value={summary.max_drawdown_pct != null ? `${fmt(summary.max_drawdown_pct)}%` : '—'} valueClass="text-red-400" />
            <StatCard label="Best Day" value={summary.best_day != null ? fmt(summary.best_day, 0) : '—'} valueClass="text-emerald-400" />
            <StatCard label="Worst Day" value={summary.worst_day != null ? fmt(summary.worst_day, 0) : '—'} valueClass="text-red-400" />
          </div>

          {/* Strategy breakdown */}
          {Object.keys(strategyBreakdown).length > 0 && (
            <div className="glass-panel p-3">
              <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-2">Strategy Breakdown</div>
              <div className="flex flex-wrap gap-2">
                {Object.entries(strategyBreakdown).map(([name, stats]) => (
                  <span key={name}
                    className={`text-[10px] px-2 py-1 rounded border font-medium ${
                      stats.pnl > 0 ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30' : 'bg-red-500/10 text-red-400 border-red-500/30'
                    }`}>
                    {name}
                    <span className="ml-1 opacity-70 font-mono">{stats.trades}t {stats.win_rate?.toFixed(0)}%WR {stats.pnl > 0 ? '+' : ''}{fmt(stats.pnl, 0)}</span>
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Daily breakdown */}
          {dailyResults.length > 0 && (
            <div className="glass-panel overflow-hidden">
              <div className="px-3 py-2 border-b border-gray-800 text-[10px] text-gray-500 uppercase tracking-wider">
                Daily Breakdown
              </div>
              <div className="overflow-auto max-h-80">
                <table className="w-full text-[10px]">
                  <thead className="sticky top-0 bg-gray-900">
                    <tr className="border-b border-gray-800">
                      {['Date', 'Day', 'Trades', 'W/L', 'P&L', 'Open', 'Close'].map(h => (
                        <th key={h} className="text-left px-3 py-2 text-[9px] text-gray-600 uppercase tracking-wider font-medium">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {dailyResults.map((d, i) => {
                      const pnl = d.day_pnl ?? 0
                      return (
                        <tr key={i} className="border-b border-gray-800/40 hover:bg-gray-800/20 transition-colors">
                          <td className="px-3 py-1.5 font-mono text-gray-400">{d.date || '—'}</td>
                          <td className="px-3 py-1.5 text-gray-500">{d.day_of_week?.slice(0, 3)}</td>
                          <td className="px-3 py-1.5 font-mono text-gray-300">{d.trade_count ?? 0}</td>
                          <td className="px-3 py-1.5 font-mono text-gray-400">{d.winners ?? 0}/{d.losers ?? 0}</td>
                          <td className={`px-3 py-1.5 font-mono font-semibold ${pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            {pnl >= 0 ? '+' : ''}{fmt(pnl, 0)}
                          </td>
                          <td className="px-3 py-1.5 font-mono text-gray-500">{d.open_price ? fmt(d.open_price, 0) : '—'}</td>
                          <td className="px-3 py-1.5 font-mono text-gray-500">{d.close_price ? fmt(d.close_price, 0) : '—'}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      {/* Empty state */}
      {!running && !results && !err && (
        <div className="glass-panel p-10 text-center">
          <div className="text-2xl text-gray-700 mb-3">&#x27F3;</div>
          <div className="text-sm text-gray-500 font-medium mb-1">Time Machine</div>
          <div className="text-xs text-gray-600 max-w-md mx-auto">
            <strong>Date Range:</strong> Run a historical backtest across multiple days.
            <br />
            <strong>Single Day:</strong> Simulate one trading day with all agents communicating — Learner briefs Trader, Charting runs replay, Builder evaluates.
          </div>
        </div>
      )}
    </div>
  )
}
