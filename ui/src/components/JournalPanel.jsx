import React, { useState } from 'react'
import { useApp } from '../context/AppContext'

const TABS = ['Morning Scan', 'Trade Details', 'Filter Verdicts']

export default function JournalPanel() {
  const [activeTab, setActiveTab] = useState(0)
  const { dayData, dayLoading } = useApp()

  const journal = dayData?.journal
  const trades = dayData?.trades || []

  return (
    <div className="glass-panel flex-1 flex flex-col overflow-hidden">
      {/* Tab Bar */}
      <div className="flex items-center gap-1 px-3 pt-3 pb-2 border-b border-gray-700/50">
        {TABS.map((tab, i) => (
          <button
            key={tab}
            id={`journal-tab-${i}`}
            onClick={() => setActiveTab(i)}
            className={`tab-btn ${activeTab === i ? 'active' : ''}`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-3 text-xs">
        {dayLoading ? (
          <div className="space-y-2">
            {[...Array(4)].map((_, i) => <div key={i} className="h-4 loading-shimmer rounded w-3/4" />)}
          </div>
        ) : activeTab === 0 ? (
          <MorningScan journal={journal} />
        ) : activeTab === 1 ? (
          <TradeDetails trades={trades} />
        ) : (
          <FilterVerdicts journal={journal} />
        )}
      </div>
    </div>
  )
}

function MorningScan({ journal }) {
  if (!journal) {
    return <EmptyState message="No journal data for this day" />
  }

  const gap = journal.pre_market?.gap || {}
  const scan = journal.morning_scan || {}
  const fh = journal.first_hour || {}
  const indicators = journal['5m_indicators'] || {}

  const rows = [
    ['Gap Type', `${gap.Gap_Type?.toUpperCase() || '—'} (${gap.Gap_Pct?.toFixed(2) || 0}%)`],
    ['Regime', journal.pre_market?.regime?.toUpperCase() || '—'],
    ['Daily ATR', `${journal.pre_market?.atr?.toFixed(0) || '—'} pts`],
    ['RSI (daily)', journal.pre_market?.rsi?.toFixed(1) || '—'],
    ['Bull Streak', scan.streak?.bull || '0'],
    ['Bear Streak', scan.streak?.bear || '0'],
    ['FH Direction', fh.FH_Direction === 1 ? '▲ Bullish' : fh.FH_Direction === -1 ? '▼ Bearish' : '— Neutral'],
    ['FH Return', `${(fh.FH_Return || 0).toFixed(2)}%`],
    ['FH Strong', fh.FH_Strong === 'True' ? '✓ Yes' : '✗ No'],
    ['VWAP', indicators.vwap?.toFixed(0) || '—'],
  ]

  return (
    <div className="space-y-1.5 animate-fade-in">
      {rows.map(([label, value], i) => (
        <div key={i} className="flex items-center justify-between py-1 border-b border-gray-800/50">
          <span className="text-gray-500">{label}</span>
          <span className="font-mono text-gray-300">{value}</span>
        </div>
      ))}
    </div>
  )
}

function TradeDetails({ trades }) {
  if (!trades?.length) {
    return <EmptyState message="No trades taken on this day" />
  }

  return (
    <div className="space-y-4 animate-fade-in">
      {trades.map((t, i) => (
        <div key={i} className="space-y-1.5">
          {i > 0 && <hr className="border-gray-700 my-3" />}
          <div className="flex items-center gap-2 mb-2">
            <span className={`text-xs font-bold px-2 py-0.5 rounded ${
              t.direction === 'LONG' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'
            }`}>
              {t.direction} {t.direction === 'LONG' ? '▲' : '▼'}
            </span>
            <span className="text-gray-400 capitalize">{t.strategy?.replace(/_/g, ' ')}</span>
          </div>
          <Row label="Entry" value={`${formatTime(t.entry_time_unix)}  @  ${t.entry_price?.toLocaleString('en-IN')}`} />
          <Row label="Exit" value={`${formatTime(t.exit_time_unix)}  @  ${t.exit_price?.toLocaleString('en-IN')}  (${t.exit_reason?.replace(/_/g, ' ')})`} />
          <Row label="Stop Loss" value={t.stop_loss?.toLocaleString('en-IN', { maximumFractionDigits: 2 })} />
          <Row label="Target" value={t.target?.toLocaleString('en-IN', { maximumFractionDigits: 2 })} />
          <Row label="Quantity" value={`${t.quantity} lots`} />
          <Row label="Gross P&L" value={`₹${t.gross_pnl?.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`} color={t.gross_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'} />
          <Row label="Costs" value={`₹${Math.abs(t.costs || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`} color="text-gray-500" />
          <div className="flex items-center justify-between py-1 border-t border-gray-700 mt-1">
            <span className="text-gray-400 font-medium">Net P&L</span>
            <span className={`font-mono font-bold text-sm ${t.net_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {t.net_pnl >= 0 ? '+' : ''}₹{t.net_pnl?.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
            </span>
          </div>
        </div>
      ))}
    </div>
  )
}

function FilterVerdicts({ journal }) {
  const filter = journal?.morning_scan?.filter_verdict
  if (!filter) {
    return <EmptyState message="No filter verdict data" />
  }

  const filters = [
    { name: 'Combined Long', value: filter.combined_long || 0 },
    { name: 'Combined Short', value: filter.combined_short || 0 },
  ]

  // Extract individual filter scores from strategies_evaluated if available
  const stratEvals = journal?.strategies_evaluated || []
  const blocked = filter.blocked

  return (
    <div className="space-y-3 animate-fade-in">
      {filters.map((f, i) => (
        <div key={i} className="space-y-1">
          <div className="flex justify-between">
            <span className="text-gray-400">{f.name}</span>
            <span className="font-mono text-gray-300">{f.value.toFixed(4)}</span>
          </div>
          <div className="filter-bar">
            <div
              className="filter-bar-fill"
              style={{
                width: `${Math.min(f.value / 1.5 * 100, 100)}%`,
                backgroundColor: f.value >= 0.8 ? '#10b981' : f.value >= 0.5 ? '#f59e0b' : '#ef4444',
              }}
            />
          </div>
        </div>
      ))}

      <div className="flex items-center justify-between pt-3 border-t border-gray-700">
        <span className="text-gray-400 font-medium">Trade Allowed</span>
        <span className={`font-bold ${!blocked ? 'text-emerald-400' : 'text-red-400'}`}>
          {!blocked ? '✓ YES' : '✗ BLOCKED'}
        </span>
      </div>

      {stratEvals.length > 0 && (
        <div className="mt-3 pt-3 border-t border-gray-700">
          <div className="text-[10px] text-gray-500 uppercase mb-2">Strategy Signals</div>
          {stratEvals.slice(0, 3).map((ev, i) => (
            <div key={i} className="flex items-center justify-between py-1">
              <span className="text-gray-400 text-[10px]">
                {ev.selected ? ev.selected.strategy?.replace(/_/g, ' ') : ev.reason?.replace(/_/g, ' ')}
              </span>
              <span className={`font-mono text-[10px] ${ev.selected ? 'text-emerald-400' : 'text-gray-600'}`}>
                {ev.selected ? `${ev.selected.score?.toFixed(4)} ✓` : 'rejected'}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function Row({ label, value, color = 'text-gray-300' }) {
  return (
    <div className="flex items-center justify-between py-0.5">
      <span className="text-gray-500">{label}</span>
      <span className={`font-mono ${color}`}>{value}</span>
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

function formatTime(unix) {
  if (!unix) return '—'
  const d = new Date(unix * 1000)
  return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' })
}
