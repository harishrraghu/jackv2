import React, { useState, useMemo } from 'react'
import { useApp } from '../context/AppContext'

const TABS = ['Shortcomings', 'Strategy Stats', 'Calendar Heatmap']

export default function AnalysisPanel() {
  const [activeTab, setActiveTab] = useState(0)
  const { shortcomings, metrics, days, setSelectedDate, loading } = useApp()

  return (
    <div className="glass-panel flex-1 flex flex-col overflow-hidden">
      {/* Tab Bar */}
      <div className="flex items-center gap-1 px-3 pt-3 pb-2 border-b border-gray-700/50">
        {TABS.map((tab, i) => (
          <button
            key={tab}
            id={`analysis-tab-${i}`}
            onClick={() => setActiveTab(i)}
            className={`tab-btn ${activeTab === i ? 'active' : ''}`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-3 text-xs">
        {loading ? (
          <div className="space-y-2">
            {[...Array(4)].map((_, i) => <div key={i} className="h-4 loading-shimmer rounded w-3/4" />)}
          </div>
        ) : activeTab === 0 ? (
          <ShortcomingsTab flags={shortcomings?.flags || []} />
        ) : activeTab === 1 ? (
          <StrategyStatsTab metrics={metrics} />
        ) : (
          <CalendarHeatmap days={days} onSelectDate={setSelectedDate} />
        )}
      </div>
    </div>
  )
}

function ShortcomingsTab({ flags }) {
  if (!flags.length) {
    return <EmptyState message="No shortcomings data — run simulation first" />
  }

  const severityIcon = { HIGH: '🔴', MEDIUM: '🟡', LOW: '🔵' }
  const severityClass = { HIGH: 'severity-high', MEDIUM: 'severity-medium', LOW: 'severity-low' }

  return (
    <div className="space-y-3 animate-fade-in">
      {flags.map((flag, i) => (
        <div key={i} className={`rounded-lg p-3 ${severityClass[flag.severity] || 'severity-low'}`}>
          <div className="flex items-center gap-2 mb-1.5">
            <span>{severityIcon[flag.severity] || '🔵'}</span>
            <span className="font-semibold text-xs uppercase tracking-wide">{flag.severity}</span>
            <span className="text-gray-400">·</span>
            <span className="text-gray-300">{flag.category}</span>
          </div>
          <p className="text-gray-300 text-[11px] mb-1.5 leading-relaxed">{flag.message}</p>
          <p className="text-gray-500 text-[10px] italic">💡 {flag.recommendation}</p>
        </div>
      ))}
    </div>
  )
}

function StrategyStatsTab({ metrics }) {
  const byStrategy = metrics?.by_strategy || {}
  const byDow = metrics?.by_day_of_week || {}

  if (!Object.keys(byStrategy).length) {
    return <EmptyState message="No strategy data — run simulation first" />
  }

  return (
    <div className="space-y-4 animate-fade-in">
      {/* Strategy Table */}
      <div>
        <div className="text-[10px] text-gray-500 uppercase mb-2 tracking-wider">By Strategy</div>
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-gray-500 border-b border-gray-700">
                <th className="text-left py-1.5 pr-3">Strategy</th>
                <th className="text-right py-1.5 px-2">Trades</th>
                <th className="text-right py-1.5 px-2">Win%</th>
                <th className="text-right py-1.5 pl-2">Net P&L</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(byStrategy).map(([name, data]) => (
                <tr key={name} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                  <td className="py-1.5 pr-3 text-gray-300 capitalize">{name.replace(/_/g, ' ')}</td>
                  <td className="text-right py-1.5 px-2 font-mono text-gray-400">{data.trades}</td>
                  <td className={`text-right py-1.5 px-2 font-mono ${data.win_rate > 55 ? 'text-emerald-400' : 'text-gray-400'}`}>
                    {data.win_rate?.toFixed(1)}%
                  </td>
                  <td className={`text-right py-1.5 pl-2 font-mono font-medium ${data.net_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    ₹{(data.net_pnl / 1000).toFixed(1)}k
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Day of Week */}
      <div>
        <div className="text-[10px] text-gray-500 uppercase mb-2 tracking-wider">By Day of Week</div>
        <div className="grid grid-cols-5 gap-2">
          {['MON', 'TUE', 'WED', 'THU', 'FRI'].map(dow => {
            const data = byDow[dow] || { trades: 0, win_rate: 0 }
            return (
              <div key={dow} className="text-center p-2 rounded-lg bg-gray-800/40">
                <div className="text-[10px] text-gray-500 mb-1">{dow}</div>
                <div className={`text-xs font-bold font-mono ${data.win_rate > 55 ? 'text-emerald-400' : data.win_rate > 0 ? 'text-gray-300' : 'text-gray-600'}`}>
                  {data.win_rate?.toFixed(0)}%
                </div>
                <div className="text-[9px] text-gray-600">{data.trades} trades</div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function CalendarHeatmap({ days, onSelectDate }) {
  const months = useMemo(() => {
    if (!days.length) return []

    const grouped = {}
    for (const day of days) {
      const [year, month] = day.date.split('-')
      const key = `${year}-${month}`
      if (!grouped[key]) grouped[key] = []
      grouped[key].push(day)
    }

    return Object.entries(grouped).map(([key, days]) => ({
      label: key,
      days,
    }))
  }, [days])

  if (!months.length) {
    return <EmptyState message="No calendar data" />
  }

  const getColor = (day) => {
    if (!day.has_trade) return '#374151'
    if (day.net_pnl > 3000) return '#059669'
    if (day.net_pnl > 0) return '#34d399'
    if (day.net_pnl > -3000) return '#f87171'
    return '#dc2626'
  }

  return (
    <div className="space-y-2 animate-fade-in">
      <div className="flex items-center gap-3 mb-2">
        <span className="text-[9px] text-gray-500">Loss</span>
        <div className="flex gap-0.5">
          {['#dc2626', '#f87171', '#374151', '#34d399', '#059669'].map(c => (
            <div key={c} className="w-3 h-3 rounded-sm" style={{ backgroundColor: c }} />
          ))}
        </div>
        <span className="text-[9px] text-gray-500">Profit</span>
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-2">
        {months.slice(-12).map(month => (
          <div key={month.label}>
            <div className="text-[9px] text-gray-500 mb-1">{month.label}</div>
            <div className="flex flex-wrap gap-0.5" style={{ maxWidth: '120px' }}>
              {month.days.map(day => (
                <div
                  key={day.date}
                  onClick={() => onSelectDate(day.date)}
                  className="heatmap-cell"
                  style={{ backgroundColor: getColor(day) }}
                  title={`${day.date}: ${day.has_trade ? `₹${day.net_pnl.toFixed(0)}` : 'No trade'}`}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function EmptyState({ message }) {
  return (
    <div className="flex items-center justify-center h-full text-gray-600 text-sm">
      {message}
    </div>
  )
}
