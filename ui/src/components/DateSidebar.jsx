import React, { useRef, useEffect } from 'react'
import { useApp } from '../context/AppContext'
import EquityMini from './EquityMini'

export default function DateSidebar() {
  const { days, selectedDate, setSelectedDate, loading, equity } = useApp()
  const listRef = useRef(null)
  const selectedRef = useRef(null)

  // Auto-scroll to selected date
  useEffect(() => {
    if (selectedRef.current) {
      selectedRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }, [selectedDate])

  // Summary calculations
  const tradeDays = days.filter(d => d.has_trade)
  const totalPnl = tradeDays.reduce((sum, d) => sum + d.net_pnl, 0)
  const wins = tradeDays.filter(d => d.result === 'win').length
  const winRate = tradeDays.length > 0 ? (wins / tradeDays.length * 100) : 0

  if (loading) {
    return (
      <aside className="w-52 bg-gray-900 border-r border-gray-800 flex flex-col">
        <div className="p-3 space-y-2">
          {[...Array(8)].map((_, i) => (
            <div key={i} className="h-8 loading-shimmer rounded" />
          ))}
        </div>
      </aside>
    )
  }

  return (
    <aside className="w-52 bg-gray-900/80 border-r border-gray-800 flex flex-col">
      {/* Mini Equity Chart */}
      <div className="p-3 border-b border-gray-800">
        <EquityMini />
        <div className="flex items-center justify-between mt-2 px-1">
          <div>
            <div className={`text-sm font-bold font-mono ${totalPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              ₹{Math.abs(totalPnl) >= 100000 ? `${(totalPnl / 100000).toFixed(1)}L` : totalPnl.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
            </div>
            <div className="text-[9px] text-gray-500 uppercase tracking-wider">Total P&L</div>
          </div>
          <div className="text-right">
            <div className={`text-sm font-bold font-mono ${winRate > 55 ? 'text-emerald-400' : 'text-gray-400'}`}>
              {winRate.toFixed(0)}%
            </div>
            <div className="text-[9px] text-gray-500 uppercase tracking-wider">Win Rate</div>
          </div>
        </div>
      </div>

      {/* Day List */}
      <div ref={listRef} className="flex-1 overflow-y-auto">
        {days.map((day) => {
          const isSelected = day.date === selectedDate
          const resultClass = day.has_trade ? day.result : 'no-trade'

          return (
            <div
              key={day.date}
              ref={isSelected ? selectedRef : null}
              onClick={() => setSelectedDate(day.date)}
              className={`day-item ${resultClass} ${isSelected ? 'selected' : ''}`}
            >
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-[10px] text-gray-500 font-mono w-7 shrink-0">
                  {day.day_of_week}
                </span>
                <span className="text-xs text-gray-300 truncate">
                  {formatDate(day.date)}
                </span>
              </div>
              <div className={`text-xs font-mono font-medium shrink-0 ${
                !day.has_trade ? 'text-gray-600' :
                day.net_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'
              }`}>
                {day.has_trade
                  ? `${day.net_pnl >= 0 ? '+' : ''}₹${Math.abs(day.net_pnl) >= 1000
                      ? `${(day.net_pnl / 1000).toFixed(1)}k`
                      : day.net_pnl.toFixed(0)}`
                  : '—'}
              </div>
            </div>
          )
        })}
      </div>

      {/* Footer Stats */}
      <div className="p-3 border-t border-gray-800 text-[10px] text-gray-500 flex justify-between">
        <span>{days.length} days</span>
        <span>{tradeDays.length} traded</span>
      </div>
    </aside>
  )
}

function formatDate(dateStr) {
  const d = new Date(dateStr + 'T00:00:00')
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })
}
