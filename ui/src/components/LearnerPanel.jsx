import React, { useState, useEffect, useCallback } from 'react'
import { fetchDiscoveries, fetchInbox, sendMessage } from '../api/client'

const TABS = ['Discoveries', 'Mine Data', 'Sources', 'Inbox']

const STATUS_STYLES = {
  PENDING:   'bg-amber-500/15 text-amber-400 border-amber-500/30',
  VALIDATED: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  REJECTED:  'bg-red-500/15 text-red-400 border-red-500/30',
}

const SOURCE_ICONS = {
  YouTube:   '▶',
  PDF:       '⬡',
  Web:       '◉',
  'Own Data': '◈',
}

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

/* ---- Discoveries Tab ---- */
function DiscoveriesTab({ data }) {
  if (!data) return <div className="text-xs text-gray-500 italic py-6 text-center">Loading discoveries…</div>
  if (data.length === 0) return <div className="text-xs text-gray-500 italic py-6 text-center">No discoveries yet</div>

  return (
    <div className="grid grid-cols-2 gap-3">
      {data.map((d, i) => {
        const status = d.status || 'PENDING'
        const icon = SOURCE_ICONS[d.source_type] || '◇'
        return (
          <div key={i} className="glass-panel p-3 space-y-2">
            <div className="flex items-start justify-between gap-2">
              <div className="flex items-center gap-1.5 min-w-0">
                <span className="text-gray-500 text-[10px]">{icon}</span>
                <span className="text-[10px] text-gray-500">{d.source_type || 'Unknown'}</span>
              </div>
              <span className={`shrink-0 text-[9px] font-bold px-1.5 py-0.5 rounded border ${STATUS_STYLES[status] || STATUS_STYLES.PENDING}`}>
                {status}
              </span>
            </div>

            <div className="text-[10px] text-gray-300 leading-relaxed">{d.claim || d.description || '—'}</div>

            <div className="grid grid-cols-2 gap-2">
              {d.indicator && (
                <div>
                  <div className="text-[9px] text-gray-600 uppercase">Indicator</div>
                  <div className="text-[10px] text-blue-400 font-mono">{d.indicator}</div>
                </div>
              )}
              {d.condition && (
                <div>
                  <div className="text-[9px] text-gray-600 uppercase">Condition</div>
                  <div className="text-[10px] text-gray-400 font-mono truncate">{d.condition}</div>
                </div>
              )}
            </div>

            {d.confidence != null && (
              <div className="flex items-center gap-2">
                <div className="text-[9px] text-gray-600 uppercase w-16">Confidence</div>
                <div className="flex-1 h-1 bg-gray-700 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${d.confidence >= 0.7 ? 'bg-emerald-500' : d.confidence >= 0.4 ? 'bg-amber-500' : 'bg-red-500'}`}
                    style={{ width: `${Math.min(100, d.confidence * 100)}%` }}
                  />
                </div>
                <span className="text-[9px] font-mono text-gray-500">{(d.confidence * 100).toFixed(0)}%</span>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

/* ---- Mine Data Tab ---- */
function MineDataTab() {
  const [running, setRunning] = useState(false)
  const [results, setResults] = useState([])
  const [err, setErr] = useState(null)

  const run = async () => {
    setRunning(true)
    setErr(null)
    try {
      // POST to trigger mining; adjust endpoint as needed
      const res = await fetch('/api/learner/mine', { method: 'POST' })
      const data = await res.json()
      setResults(Array.isArray(data) ? data : [data])
    } catch (e) {
      setErr(e.message)
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="glass-panel p-4 flex items-center gap-4">
        <div className="flex-1">
          <div className="text-xs font-semibold text-gray-300 mb-1">Mine Own Trade Data</div>
          <div className="text-[10px] text-gray-500">Run SQL analysis on historical trades to discover patterns</div>
        </div>
        <button
          onClick={run}
          disabled={running}
          className={`px-4 py-2 rounded-lg text-xs font-semibold transition-all ${
            running
              ? 'bg-gray-700 text-gray-400 cursor-wait'
              : 'bg-blue-600 hover:bg-blue-500 text-white shadow-lg shadow-blue-600/20'
          }`}
        >
          {running ? 'Mining…' : '⬡ Run Mining'}
        </button>
      </div>

      {err && <div className="text-xs text-red-400 glass-panel p-3">{err}</div>}

      {results.length > 0 && (
        <div className="grid grid-cols-3 gap-3">
          {results.map((r, i) => (
            <div key={i} className="glass-panel p-3 space-y-1.5">
              {r.label && <div className="text-[10px] text-gray-400 font-semibold">{r.label}</div>}
              {r.sample_size != null && (
                <div className="flex justify-between">
                  <span className="text-[9px] text-gray-600 uppercase">Samples</span>
                  <span className="text-[10px] font-mono text-gray-300">{r.sample_size}</span>
                </div>
              )}
              {r.win_rate != null && (
                <div className="flex justify-between">
                  <span className="text-[9px] text-gray-600 uppercase">Win Rate</span>
                  <span className={`text-[10px] font-mono font-bold ${r.win_rate >= 0.5 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {(r.win_rate * 100).toFixed(1)}%
                  </span>
                </div>
              )}
              {r.p_value != null && (
                <div className="flex justify-between">
                  <span className="text-[9px] text-gray-600 uppercase">p-value</span>
                  <span className={`text-[10px] font-mono ${r.p_value < 0.05 ? 'text-emerald-400' : 'text-amber-400'}`}>
                    {r.p_value.toFixed(4)}
                  </span>
                </div>
              )}
              {r.confidence != null && (
                <span className={`text-[9px] px-1.5 py-0.5 rounded border font-bold inline-block ${
                  r.confidence >= 0.7 ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                  : 'bg-amber-500/15 text-amber-400 border-amber-500/30'
                }`}>
                  {r.confidence >= 0.7 ? 'HIGH' : 'MED'} CONFIDENCE
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ---- Sources Tab ---- */
function SourcesTab() {
  const [url, setUrl] = useState('')
  const [type, setType] = useState('YouTube')
  const [queue, setQueue] = useState([])
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState(null)

  const submit = async () => {
    if (!url.trim()) return
    setSubmitting(true)
    setErr(null)
    try {
      await sendMessage({ to: 'learner', type: 'process_source', url, source_type: type })
      setQueue(q => [{ url, type, status: 'queued', ts: new Date().toLocaleTimeString() }, ...q])
      setUrl('')
    } catch (e) {
      setErr(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-3">
      <div className="glass-panel p-4 space-y-3">
        <div className="text-xs font-semibold text-gray-300">Submit a Source</div>
        <div className="flex gap-2">
          <select
            value={type}
            onChange={e => setType(e.target.value)}
            className="bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-xs text-gray-300 focus:outline-none focus:border-blue-500"
          >
            {['YouTube', 'Web', 'PDF'].map(t => <option key={t}>{t}</option>)}
          </select>
          <input
            type="text"
            value={url}
            onChange={e => setUrl(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && submit()}
            placeholder="Paste YouTube URL or web link…"
            className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500"
          />
          <button
            onClick={submit}
            disabled={submitting || !url.trim()}
            className="px-4 py-1.5 rounded-lg text-xs font-semibold bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-40 transition-colors"
          >
            {submitting ? '…' : 'Submit'}
          </button>
        </div>
        {err && <div className="text-[10px] text-red-400">{err}</div>}
      </div>

      {queue.length > 0 && (
        <div className="glass-panel overflow-hidden">
          <div className="px-3 py-2 border-b border-gray-800 text-[10px] text-gray-500 uppercase tracking-wider">Processing Queue</div>
          <div className="divide-y divide-gray-800/50">
            {queue.map((item, i) => (
              <div key={i} className="flex items-center justify-between px-3 py-2">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-[10px] text-gray-600">{SOURCE_ICONS[item.type]}</span>
                  <span className="text-[10px] text-gray-400 truncate">{item.url}</span>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className="text-[9px] text-gray-600">{item.ts}</span>
                  <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 border border-amber-500/30">
                    {item.status}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

/* ---- Inbox Tab ---- */
function InboxTab({ data }) {
  if (!data || data.length === 0)
    return <div className="text-xs text-gray-500 italic py-6 text-center">Learner inbox is empty</div>

  return (
    <div className="space-y-2">
      {data.map((msg, i) => (
        <div key={i} className="glass-panel p-3 flex gap-3">
          <div className="w-1 rounded-full bg-blue-500/60 shrink-0" />
          <div className="min-w-0 space-y-1">
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-semibold text-gray-300">{msg.from || msg.type || 'system'}</span>
              {msg.timestamp && (
                <span className="text-[9px] text-gray-600">{msg.timestamp}</span>
              )}
            </div>
            <div className="text-[10px] text-gray-400 leading-relaxed">{msg.body || msg.content || JSON.stringify(msg)}</div>
          </div>
        </div>
      ))}
    </div>
  )
}

/* ---- Main ---- */
export default function LearnerPanel() {
  const [tab, setTab] = useState('Discoveries')
  const [discoveries, setDiscoveries] = useState(null)
  const [inbox, setInbox] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(null)

  const load = useCallback(async (t) => {
    setLoading(true)
    setErr(null)
    try {
      if (t === 'Discoveries') {
        const d = await fetchDiscoveries()
        setDiscoveries(Array.isArray(d) ? d : [])
      } else if (t === 'Inbox') {
        const d = await fetchInbox('learner')
        setInbox(Array.isArray(d) ? d : [])
      }
    } catch (e) {
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const needLoad = (tab === 'Discoveries' && discoveries == null) || (tab === 'Inbox' && inbox == null)
    if (needLoad) load(tab)
  }, [tab, load, discoveries, inbox])

  const renderTab = () => {
    if (loading) return <div className="py-10 text-center text-xs text-gray-500">Loading…</div>
    if (tab === 'Discoveries') return <DiscoveriesTab data={discoveries} />
    if (tab === 'Mine Data') return <MineDataTab />
    if (tab === 'Sources') return <SourcesTab />
    return <InboxTab data={inbox} />
  }

  return (
    <div className="flex-1 overflow-auto p-4 space-y-3">
      <div className="glass-panel p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-200">Learner Activity</h2>
          {err && <span className="text-[10px] text-red-400">{err}</span>}
        </div>
        <TabBar active={tab} onChange={setTab} />
        <div className="pt-1">{renderTab()}</div>
      </div>
    </div>
  )
}
