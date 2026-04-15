import React, { useState, useEffect, useCallback } from 'react'
import { fetchLiveStatus, fetchPositions, fetchFunds, fetchLivePrice } from '../api/client'

const PHASE_STYLES = {
  PRE_MARKET:  { color: 'text-blue-400',   bg: 'bg-blue-500/10',   border: 'border-blue-500/30',  dot: 'bg-blue-400'   },
  OBSERVING:   { color: 'text-gray-400',   bg: 'bg-gray-500/10',   border: 'border-gray-500/30',  dot: 'bg-gray-400'   },
  IN_TRADE:    { color: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', dot: 'bg-emerald-400' },
  CLOSING:     { color: 'text-amber-400',  bg: 'bg-amber-500/10',  border: 'border-amber-500/30', dot: 'bg-amber-400'  },
  MARKET_CLOSED: { color: 'text-gray-500', bg: 'bg-gray-700/10',   border: 'border-gray-700/30',  dot: 'bg-gray-600'   },
}

function isMarketOpen() {
  const now = new Date()
  // convert to IST (UTC+5:30)
  const ist = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }))
  const h = ist.getHours(), m = ist.getMinutes()
  const mins = h * 60 + m
  return mins >= 9 * 60 + 15 && mins <= 15 * 60 + 30
}

function fmt(n, dec = 2) {
  if (n == null) return '—'
  return Number(n).toLocaleString('en-IN', { minimumFractionDigits: dec, maximumFractionDigits: dec })
}

function StatCard({ label, value, sub, valueClass = 'text-gray-100' }) {
  return (
    <div className="glass-panel p-3 flex flex-col gap-1 min-w-0">
      <div className="text-[10px] text-gray-500 uppercase tracking-wider">{label}</div>
      <div className={`text-lg font-bold font-mono leading-none ${valueClass}`}>{value}</div>
      {sub && <div className="text-[10px] text-gray-500 mt-0.5">{sub}</div>}
    </div>
  )
}

function ProgressBar({ value, max = 100, color = 'bg-blue-500' }) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100))
  return (
    <div className="flex-1 h-1 bg-gray-700/60 rounded-full overflow-hidden">
      <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
    </div>
  )
}

export default function LiveDashboard() {
  const [status, setStatus] = useState(null)
  const [positions, setPositions] = useState([])
  const [funds, setFunds] = useState(null)
  const [price, setPrice] = useState(null)
  const [lastRefresh, setLastRefresh] = useState(null)
  const [fetchErr, setFetchErr] = useState(null)
  const [killConfirm, setKillConfirm] = useState(false)
  const [marketOpen] = useState(isMarketOpen)

  const refresh = useCallback(async () => {
    try {
      const [s, p, f, pr] = await Promise.allSettled([
        fetchLiveStatus(),
        fetchPositions(),
        fetchFunds(),
        fetchLivePrice('BANKNIFTY'),
      ])
      if (s.status === 'fulfilled') setStatus(s.value)
      if (p.status === 'fulfilled') setPositions(Array.isArray(p.value) ? p.value : [])
      if (f.status === 'fulfilled') setFunds(f.value)
      if (pr.status === 'fulfilled') setPrice(pr.value)
      setFetchErr(null)
    } catch (e) {
      setFetchErr(e.message)
    }
    setLastRefresh(new Date())
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 10000)
    return () => clearInterval(id)
  }, [refresh])

  const phase = status?.phase || (marketOpen ? 'OBSERVING' : 'MARKET_CLOSED')
  const ps = PHASE_STYLES[phase] || PHASE_STYLES.OBSERVING
  const todayPnl = status?.today_pnl ?? funds?.today_pnl ?? null
  const pnlClass = todayPnl == null ? 'text-gray-400' : todayPnl >= 0 ? 'text-emerald-400' : 'text-red-400'

  const confluence = status?.confluence_scores || {}
  const checklist = status?.entry_checklist || {}
  const pos = positions[0] || null

  return (
    <div className="flex-1 overflow-auto p-4 space-y-3">
      {/* Kill switch + last refresh */}
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-gray-600">
          {lastRefresh ? `Refreshed ${lastRefresh.toLocaleTimeString('en-IN')} · auto every 10s` : 'Loading…'}
          {fetchErr && <span className="text-red-500 ml-2">· {fetchErr}</span>}
        </span>
        {!killConfirm ? (
          <button
            onClick={() => setKillConfirm(true)}
            className="px-3 py-1 rounded-lg text-xs font-semibold bg-red-900/40 text-red-400 border border-red-700/40 hover:bg-red-800/60 transition-colors"
          >
            ☠ Kill Switch
          </button>
        ) : (
          <div className="flex items-center gap-2">
            <span className="text-xs text-red-400 font-semibold">Confirm kill all positions?</span>
            <button
              onClick={() => { alert('Kill switch activated — implement POST /api/live/kill'); setKillConfirm(false) }}
              className="px-3 py-1 rounded-lg text-xs font-bold bg-red-600 text-white hover:bg-red-500 transition-colors"
            >
              YES, KILL
            </button>
            <button
              onClick={() => setKillConfirm(false)}
              className="px-3 py-1 rounded-lg text-xs text-gray-400 border border-gray-700 hover:bg-gray-800 transition-colors"
            >
              Cancel
            </button>
          </div>
        )}
      </div>

      {/* Top row: 3 cards */}
      <div className="grid grid-cols-3 gap-3">
        {/* Agent State */}
        <div className={`glass-panel p-3 border ${ps.border}`}>
          <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-2">Agent State</div>
          <div className="flex items-center gap-2 mb-2">
            <span className={`w-2 h-2 rounded-full ${ps.dot} ${phase === 'IN_TRADE' ? 'animate-pulse' : ''}`} />
            <span className={`text-sm font-bold ${ps.color}`}>{phase.replace('_', ' ')}</span>
          </div>
          <div className="text-[10px] text-gray-400 leading-relaxed">
            {status?.last_action || '—'}
          </div>
          {status?.timestamp && (
            <div className="text-[9px] text-gray-600 mt-1">{status.timestamp}</div>
          )}
        </div>

        {/* BankNifty Live */}
        <div className="glass-panel p-3">
          <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">BankNifty Spot</div>
          <div className="text-2xl font-bold font-mono text-gray-100 leading-none">
            {price?.ltp ? fmt(price.ltp, 0) : '—'}
          </div>
          {price?.change != null && (
            <div className={`text-xs font-mono mt-1 ${price.change >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {price.change >= 0 ? '+' : ''}{fmt(price.change, 0)}
              {price.change_pct != null && (
                <span className="ml-1 opacity-70">({price.change_pct >= 0 ? '+' : ''}{fmt(price.change_pct)}%)</span>
              )}
            </div>
          )}
          <div className="grid grid-cols-4 gap-1 mt-2">
            {['open', 'high', 'low', 'close'].map(k => (
              <div key={k} className="text-center">
                <div className="text-[8px] text-gray-600 uppercase">{k[0]}</div>
                <div className="text-[10px] font-mono text-gray-300">{price?.[k] ? fmt(price[k], 0) : '—'}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Account */}
        <div className="glass-panel p-3">
          <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-2">Account</div>
          <div className="space-y-1.5">
            <div className="flex justify-between items-center">
              <span className="text-[10px] text-gray-500">Available</span>
              <span className="text-xs font-mono text-gray-200">₹{funds?.available != null ? fmt(funds.available, 0) : '—'}</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-[10px] text-gray-500">Positions</span>
              <span className="text-xs font-mono text-gray-200">{positions.length}</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-[10px] text-gray-500">Today P&amp;L</span>
              <span className={`text-xs font-mono font-semibold ${pnlClass}`}>
                {todayPnl != null ? `₹${fmt(todayPnl, 0)}` : '—'}
              </span>
            </div>
            {funds?.used != null && (
              <div className="flex justify-between items-center">
                <span className="text-[10px] text-gray-500">Margin Used</span>
                <span className="text-xs font-mono text-gray-400">₹{fmt(funds.used, 0)}</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Open Position */}
      {pos ? (
        <div className="glass-panel p-3 border border-emerald-700/30">
          <div className="flex items-center justify-between mb-2">
            <div className="text-[10px] text-gray-500 uppercase tracking-wider">Open Position</div>
            <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
              pos.direction === 'LONG'
                ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                : 'bg-red-500/20 text-red-400 border border-red-500/30'
            }`}>{pos.direction || '—'}</span>
          </div>
          <div className="grid grid-cols-7 gap-3">
            {[
              { label: 'Strike', value: pos.strike || pos.symbol },
              { label: 'Entry', value: pos.entry_price != null ? `₹${fmt(pos.entry_price)}` : '—' },
              { label: 'Current', value: pos.current_price != null ? `₹${fmt(pos.current_price)}` : '—' },
              { label: 'Unrealized P&L', value: pos.unrealized_pnl != null ? `₹${fmt(pos.unrealized_pnl, 0)}` : '—',
                cls: pos.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400' },
              { label: 'Stop Loss', value: pos.sl != null ? `₹${fmt(pos.sl)}` : '—', cls: 'text-red-400' },
              { label: 'Target', value: pos.target != null ? `₹${fmt(pos.target)}` : '—', cls: 'text-emerald-400' },
              { label: 'Conviction', value: pos.conviction != null ? `${fmt(pos.conviction * 100, 0)}%` : '—', cls: 'text-blue-400' },
            ].map(item => (
              <div key={item.label}>
                <div className="text-[9px] text-gray-600 uppercase mb-0.5">{item.label}</div>
                <div className={`text-xs font-mono font-semibold ${item.cls || 'text-gray-200'}`}>{item.value}</div>
              </div>
            ))}
          </div>
          {pos.time_in_trade && (
            <div className="mt-1.5 text-[9px] text-gray-600">In trade: {pos.time_in_trade}</div>
          )}
        </div>
      ) : (
        <div className="glass-panel p-3 border border-dashed border-gray-700/40 text-center text-[10px] text-gray-600">
          No open positions
        </div>
      )}

      {/* Bottom: confluence + checklist */}
      <div className="grid grid-cols-2 gap-3">
        {/* Confluence Scores */}
        <div className="glass-panel p-3">
          <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-2">Confluence Scores</div>
          {Object.keys(confluence).length === 0 ? (
            <div className="text-[10px] text-gray-600 italic">No data — waiting for market data</div>
          ) : (
            <div className="space-y-1.5">
              {Object.entries(confluence).map(([key, val]) => (
                <div key={key} className="flex items-center gap-2">
                  <span className="text-[10px] text-gray-400 w-28 truncate capitalize">{key.replace(/_/g, ' ')}</span>
                  <ProgressBar
                    value={typeof val === 'number' ? val : 0}
                    max={1}
                    color={val >= 0.7 ? 'bg-emerald-500' : val >= 0.4 ? 'bg-amber-500' : 'bg-gray-600'}
                  />
                  <span className="text-[10px] font-mono text-gray-400 w-8 text-right">
                    {typeof val === 'number' ? `${Math.round(val * 100)}%` : '—'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Entry Checklist */}
        <div className="glass-panel p-3">
          <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-2">Entry Checklist</div>
          {Object.keys(checklist).length === 0 ? (
            <div className="text-[10px] text-gray-600 italic">No data — waiting for market data</div>
          ) : (
            <div className="space-y-1.5">
              {Object.entries(checklist).map(([key, gate]) => {
                const passed = typeof gate === 'boolean' ? gate : gate?.passed
                const reason = typeof gate === 'object' ? gate?.reason : null
                return (
                  <div key={key} className="flex items-start gap-2">
                    <span className={`text-xs mt-0.5 ${passed ? 'text-emerald-400' : 'text-red-400'}`}>
                      {passed ? '✓' : '✗'}
                    </span>
                    <div className="min-w-0">
                      <div className="text-[10px] text-gray-300 capitalize">{key.replace(/_/g, ' ')}</div>
                      {reason && <div className="text-[9px] text-gray-600 truncate">{reason}</div>}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* Market closed banner */}
      {!marketOpen && (
        <div className="glass-panel p-3 text-center border border-gray-700/30">
          <div className="text-xs text-gray-500">Market closed · 09:15 – 15:30 IST</div>
        </div>
      )}
    </div>
  )
}
