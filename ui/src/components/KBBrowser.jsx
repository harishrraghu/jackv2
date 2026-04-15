import React, { useState, useEffect } from 'react'
import { fetchKBStrategies, fetchKBBehaviors, fetchKBRisk, fetchKBPerformance } from '../api/client'

const TABS = ['Strategies', 'Behavior', 'Risk', 'Performance']

function TabBar({ active, onChange }) {
  return (
    <div className="flex gap-1 border-b border-gray-800 pb-0">
      {TABS.map(t => (
        <button
          key={t}
          onClick={() => onChange(t)}
          className={`px-4 py-2 text-xs font-medium border-b-2 -mb-px transition-colors ${
            active === t
              ? 'border-blue-500 text-blue-400'
              : 'border-transparent text-gray-500 hover:text-gray-300'
          }`}
        >
          {t}
        </button>
      ))}
    </div>
  )
}

function ConfidenceBar({ value }) {
  const pct = Math.min(100, Math.max(0, (value || 0) * 100))
  const color = pct >= 70 ? 'bg-emerald-500' : pct >= 45 ? 'bg-amber-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1 bg-gray-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] font-mono text-gray-400 w-8">{pct.toFixed(0)}%</span>
    </div>
  )
}

function WinRateBadge({ value }) {
  if (value == null) return <span className="text-gray-600">—</span>
  const pct = (value * 100).toFixed(1)
  const color = value >= 0.6 ? 'text-emerald-400 border-emerald-500/40 bg-emerald-500/10'
    : value >= 0.45 ? 'text-amber-400 border-amber-500/40 bg-amber-500/10'
    : 'text-red-400 border-red-500/40 bg-red-500/10'
  return (
    <span className={`text-xs font-mono font-bold px-2 py-0.5 rounded-full border ${color}`}>{pct}%</span>
  )
}

/* ---- Strategies Tab ---- */
function StrategiesTab({ data }) {
  if (!data || data.length === 0)
    return <div className="text-xs text-gray-500 italic py-6 text-center">No active strategies in KB</div>

  return (
    <div className="grid grid-cols-2 gap-3">
      {data.map((s, i) => (
        <div key={i} className="glass-panel p-3 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-gray-200">{s.name || s.id || `Strategy ${i + 1}`}</span>
            <WinRateBadge value={s.win_rate} />
          </div>

          {s.time_window && (
            <div className="text-[10px] text-gray-500">
              Window: <span className="text-gray-300">{s.time_window}</span>
            </div>
          )}

          <div className="flex gap-4">
            {s.avg_rr != null && (
              <div>
                <div className="text-[9px] text-gray-600 uppercase">Avg R:R</div>
                <div className="text-xs font-mono text-blue-400">{Number(s.avg_rr).toFixed(2)}</div>
              </div>
            )}
            {s.sample_size != null && (
              <div>
                <div className="text-[9px] text-gray-600 uppercase">Samples</div>
                <div className="text-xs font-mono text-gray-300">{s.sample_size}</div>
              </div>
            )}
          </div>

          {s.confidence != null && (
            <div>
              <div className="text-[9px] text-gray-600 uppercase mb-1">Confidence</div>
              <ConfidenceBar value={s.confidence} />
            </div>
          )}

          {s.best_conditions && s.best_conditions.length > 0 && (
            <div>
              <div className="text-[9px] text-gray-600 uppercase mb-1">Best conditions</div>
              <div className="flex flex-wrap gap-1">
                {s.best_conditions.map((c, j) => (
                  <span key={j} className="text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">{c}</span>
                ))}
              </div>
            </div>
          )}

          {s.avoid_conditions && s.avoid_conditions.length > 0 && (
            <div>
              <div className="text-[9px] text-gray-600 uppercase mb-1">Avoid when</div>
              <div className="flex flex-wrap gap-1">
                {s.avoid_conditions.map((c, j) => (
                  <span key={j} className="text-[9px] px-1.5 py-0.5 rounded bg-red-500/10 text-red-400 border border-red-500/20">{c}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

/* ---- Behavior Tab ---- */
function BehaviorTab({ data }) {
  const [open, setOpen] = useState(null)
  if (!data) return <div className="text-xs text-gray-500 italic py-6 text-center">No behavior data</div>

  const sections = Object.entries(data)
  return (
    <div className="space-y-2">
      {sections.map(([key, val]) => {
        const isOpen = open === key
        return (
          <div key={key} className="glass-panel overflow-hidden">
            <button
              onClick={() => setOpen(isOpen ? null : key)}
              className="w-full flex items-center justify-between px-3 py-2 text-left"
            >
              <span className="text-xs font-semibold text-gray-300 capitalize">{key.replace(/_/g, ' ')}</span>
              <span className="text-gray-600 text-xs">{isOpen ? '▲' : '▼'}</span>
            </button>
            {isOpen && (
              <div className="px-3 pb-3 border-t border-gray-800/50">
                {Array.isArray(val) ? (
                  <div className="space-y-1.5 pt-2">
                    {val.map((item, i) => (
                      <div key={i} className="text-[10px] text-gray-400 bg-gray-800/40 rounded p-2">
                        {typeof item === 'string' ? item : JSON.stringify(item, null, 2)}
                      </div>
                    ))}
                  </div>
                ) : typeof val === 'object' ? (
                  <div className="grid grid-cols-2 gap-2 pt-2">
                    {Object.entries(val).map(([k, v]) => (
                      <div key={k} className="bg-gray-800/40 rounded p-2">
                        <div className="text-[9px] text-gray-600 uppercase mb-0.5 capitalize">{k.replace(/_/g, ' ')}</div>
                        <div className="text-[10px] text-gray-300 font-mono">
                          {typeof v === 'number' ? v.toFixed(3) : String(v)}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-[10px] text-gray-400 pt-2">{String(val)}</div>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

/* ---- Risk Tab ---- */
function RiskTab({ data }) {
  if (!data) return <div className="text-xs text-gray-500 italic py-6 text-center">No risk rules loaded</div>

  const renderValue = (v) => {
    if (typeof v === 'number') {
      const isPercent = v > 0 && v < 1
      return (
        <span className="font-mono font-bold text-amber-400">
          {isPercent ? `${(v * 100).toFixed(1)}%` : v}
        </span>
      )
    }
    if (typeof v === 'boolean') return <span className={v ? 'text-emerald-400' : 'text-red-400'}>{String(v)}</span>
    return <span className="text-gray-300">{String(v)}</span>
  }

  const renderBlock = (block, depth = 0) => {
    if (typeof block !== 'object' || block === null) return renderValue(block)
    return (
      <div className={`space-y-1 ${depth > 0 ? 'pl-3 border-l border-gray-700/40 mt-1' : ''}`}>
        {Object.entries(block).map(([k, v]) => (
          <div key={k}>
            {typeof v === 'object' && v !== null && !Array.isArray(v) ? (
              <>
                <div className="text-[10px] text-gray-400 font-semibold capitalize mt-1.5">{k.replace(/_/g, ' ')}</div>
                {renderBlock(v, depth + 1)}
              </>
            ) : (
              <div className="flex items-center justify-between py-0.5">
                <span className="text-[10px] text-gray-500 capitalize">{k.replace(/_/g, ' ')}</span>
                <span className="text-[10px]">{renderValue(v)}</span>
              </div>
            )}
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="glass-panel p-4">
      {renderBlock(data)}
    </div>
  )
}

/* ---- Performance Tab ---- */
function PerformanceTab({ data }) {
  if (!data || data.length === 0)
    return <div className="text-xs text-gray-500 italic py-6 text-center">No recent trades in DB</div>

  const total = data.length
  const wins = data.filter(t => (t.pnl ?? t.realized_pnl ?? 0) > 0).length

  return (
    <div className="space-y-3">
      {/* Summary row */}
      <div className="flex gap-3">
        {[
          { label: 'Trades', value: total },
          { label: 'Win Rate', value: `${total ? ((wins / total) * 100).toFixed(1) : 0}%`,
            cls: wins / total >= 0.5 ? 'text-emerald-400' : 'text-red-400' },
          { label: 'Net P&L', value: `₹${data.reduce((a, t) => a + (t.pnl ?? t.realized_pnl ?? 0), 0).toFixed(0)}`,
            cls: data.reduce((a, t) => a + (t.pnl ?? t.realized_pnl ?? 0), 0) >= 0 ? 'text-emerald-400' : 'text-red-400' },
        ].map(m => (
          <div key={m.label} className="glass-panel px-4 py-2 flex-1 text-center">
            <div className={`text-sm font-bold font-mono ${m.cls || 'text-gray-200'}`}>{m.value}</div>
            <div className="text-[9px] text-gray-600 uppercase">{m.label}</div>
          </div>
        ))}
      </div>

      {/* Table */}
      <div className="glass-panel overflow-hidden">
        <table className="w-full text-[10px]">
          <thead>
            <tr className="border-b border-gray-800">
              {['Date', 'Strategy', 'Direction', 'P&L', 'Exit Reason'].map(h => (
                <th key={h} className="text-left px-3 py-2 text-[9px] text-gray-600 uppercase tracking-wider font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.map((t, i) => {
              const pnl = t.pnl ?? t.realized_pnl ?? 0
              return (
                <tr key={i} className="border-b border-gray-800/40 hover:bg-gray-800/20 transition-colors">
                  <td className="px-3 py-1.5 font-mono text-gray-400">{t.date || t.entry_time?.slice(0, 10) || '—'}</td>
                  <td className="px-3 py-1.5 text-gray-300">{t.strategy || '—'}</td>
                  <td className="px-3 py-1.5">
                    <span className={`px-1.5 py-0.5 rounded text-[9px] font-semibold ${
                      t.direction === 'LONG' ? 'bg-emerald-500/15 text-emerald-400' : 'bg-red-500/15 text-red-400'
                    }`}>{t.direction || '—'}</span>
                  </td>
                  <td className={`px-3 py-1.5 font-mono font-semibold ${pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {pnl >= 0 ? '+' : ''}₹{pnl.toFixed(0)}
                  </td>
                  <td className="px-3 py-1.5 text-gray-500">{t.exit_reason || '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/* ---- Main component ---- */
export default function KBBrowser() {
  const [tab, setTab] = useState('Strategies')
  const [strategies, setStrategies] = useState(null)
  const [behaviors, setBehaviors] = useState(null)
  const [risk, setRisk] = useState(null)
  const [performance, setPerformance] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(null)

  useEffect(() => {
    const loaders = {
      Strategies: () => fetchKBStrategies().then(setStrategies),
      Behavior:   () => fetchKBBehaviors().then(setBehaviors),
      Risk:       () => fetchKBRisk().then(setRisk),
      Performance: () => fetchKBPerformance(30).then(setPerformance),
    }
    const current = { Strategies: strategies, Behavior: behaviors, Risk: risk, Performance: performance }
    if (current[tab] != null) return
    setLoading(true)
    setErr(null)
    loaders[tab]()
      .catch(e => setErr(e.message))
      .finally(() => setLoading(false))
  }, [tab]) // eslint-disable-line

  return (
    <div className="flex-1 overflow-auto p-4 space-y-3">
      <div className="glass-panel p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-200">Knowledge Base</h2>
          {err && <span className="text-[10px] text-red-400">{err}</span>}
        </div>
        <TabBar active={tab} onChange={setTab} />
        <div className="pt-1">
          {loading ? (
            <div className="py-10 text-center text-xs text-gray-500">Loading…</div>
          ) : tab === 'Strategies' ? (
            <StrategiesTab data={strategies} />
          ) : tab === 'Behavior' ? (
            <BehaviorTab data={behaviors} />
          ) : tab === 'Risk' ? (
            <RiskTab data={risk} />
          ) : (
            <PerformanceTab data={performance} />
          )}
        </div>
      </div>
    </div>
  )
}
