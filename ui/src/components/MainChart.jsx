import React, { useEffect, useRef, useMemo } from 'react'
import { createChart, CrosshairMode, LineStyle } from 'lightweight-charts'
import { useApp } from '../context/AppContext'

const PHASE_COLORS = {
  opening_observation: '#3b82f6',
  morning_setups: '#10b981',
  first_hour_execution: '#f59e0b',
  dead_zone: '#6b7280',
  afternoon_push: '#8b5cf6',
  closing: '#ef4444',
}

const PHASE_LABELS = {
  opening_observation: 'Opening',
  morning_setups: 'Setups',
  first_hour_execution: 'Execution',
  dead_zone: 'Dead Zone',
  afternoon_push: 'Afternoon',
  closing: 'Close',
}

export default function MainChart() {
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const { dayData, dayLoading, selectedDate, navigateDay, days } = useApp()

  // Current day info
  const currentDay = useMemo(() => {
    return days.find(d => d.date === selectedDate)
  }, [days, selectedDate])

  // Trade summary
  const tradeSummary = useMemo(() => {
    if (!dayData?.trades?.length) return null
    const t = dayData.trades[0]
    return {
      strategy: t.strategy?.replace(/_/g, ' '),
      direction: t.direction,
      netPnl: t.net_pnl,
    }
  }, [dayData])

  useEffect(() => {
    if (!containerRef.current || !dayData?.candles?.length) return

    // Dispose previous
    if (chartRef.current) {
      chartRef.current.remove()
      chartRef.current = null
    }

    const container = containerRef.current
    const chart = createChart(container, {
      width: container.clientWidth,
      height: container.clientHeight,
      layout: {
        background: { color: '#0b1120' },
        textColor: '#9CA3AF',
        fontSize: 11,
        fontFamily: 'Inter, system-ui, sans-serif',
      },
      grid: {
        vertLines: { color: '#1a2332' },
        horzLines: { color: '#1a2332' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: '#4b5563', width: 1, style: LineStyle.Dashed, labelBackgroundColor: '#374151' },
        horzLine: { color: '#4b5563', width: 1, style: LineStyle.Dashed, labelBackgroundColor: '#374151' },
      },
      rightPriceScale: {
        borderColor: '#1f2937',
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      timeScale: {
        borderColor: '#1f2937',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 5,
        barSpacing: 12,
      },
    })

    chartRef.current = chart

    // ── Candlestick Series ──────────────────────────────────────────
    const candleSeries = chart.addCandlestickSeries({
      upColor: '#10B981',
      downColor: '#EF4444',
      borderUpColor: '#10B981',
      borderDownColor: '#EF4444',
      wickUpColor: '#10B981',
      wickDownColor: '#EF4444',
    })

    candleSeries.setData(dayData.candles)

    // ── Indicators ──────────────────────────────────────────────────
    if (dayData.indicators) {
      const { ema9, ema21, bb_upper, bb_middle, bb_lower } = dayData.indicators

      if (ema9?.length) {
        const ema9Series = chart.addLineSeries({
          color: '#F59E0B',
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        })
        ema9Series.setData(ema9)
      }

      if (ema21?.length) {
        const ema21Series = chart.addLineSeries({
          color: '#3B82F6',
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        })
        ema21Series.setData(ema21)
      }

      if (bb_upper?.length) {
        chart.addLineSeries({
          color: '#4B5563',
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        }).setData(bb_upper)
      }

      if (bb_middle?.length) {
        chart.addLineSeries({
          color: '#4B5563',
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        }).setData(bb_middle)
      }

      if (bb_lower?.length) {
        chart.addLineSeries({
          color: '#4B5563',
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        }).setData(bb_lower)
      }
    }

    // ── Trade Markers ───────────────────────────────────────────────
    if (dayData.trades?.length) {
      const markers = []

      for (const trade of dayData.trades) {
        const isLong = trade.direction === 'LONG'

        // Entry marker
        markers.push({
          time: trade.entry_time_unix,
          position: isLong ? 'belowBar' : 'aboveBar',
          color: '#10B981',
          shape: isLong ? 'arrowUp' : 'arrowDown',
          text: `${trade.direction} Entry`,
        })

        // Exit marker
        const exitColor = trade.exit_reason === 'target_hit' ? '#10B981' : 
                          trade.exit_reason === 'stop_loss' ? '#EF4444' : '#F59E0B'
        markers.push({
          time: trade.exit_time_unix,
          position: isLong ? 'aboveBar' : 'belowBar',
          color: exitColor,
          shape: trade.net_pnl >= 0 ? 'arrowUp' : 'arrowDown',
          text: trade.exit_reason?.replace(/_/g, ' '),
        })

        // Stop loss line
        if (trade.stop_loss) {
          const slSeries = chart.addLineSeries({
            color: '#EF4444',
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: false,
          })
          slSeries.setData([
            { time: trade.entry_time_unix, value: trade.stop_loss },
            { time: trade.exit_time_unix, value: trade.stop_loss },
          ])
        }

        // Target line
        if (trade.target) {
          const tgtSeries = chart.addLineSeries({
            color: '#10B981',
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: false,
          })
          tgtSeries.setData([
            { time: trade.entry_time_unix, value: trade.target },
            { time: trade.exit_time_unix, value: trade.target },
          ])
        }
      }

      // Sort markers by time
      markers.sort((a, b) => a.time - b.time)
      candleSeries.setMarkers(markers)
    }

    // Fit content
    chart.timeScale().fitContent()

    // Resize handler
    const handleResize = () => {
      if (chartRef.current && container) {
        chart.applyOptions({
          width: container.clientWidth,
          height: container.clientHeight,
        })
      }
    }
    const ro = new ResizeObserver(handleResize)
    ro.observe(container)

    return () => {
      ro.disconnect()
      if (chartRef.current) {
        chartRef.current.remove()
        chartRef.current = null
      }
    }
  }, [dayData])

  // Date formatting
  const formatDisplayDate = (dateStr) => {
    if (!dateStr) return ''
    const d = new Date(dateStr + 'T00:00:00')
    const days = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT']
    return `${dateStr}  ${days[d.getDay()]}`
  }

  return (
    <div className="glass-panel h-full flex flex-col overflow-hidden">
      {/* Day Navigation Bar */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-700/50">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigateDay(-1)}
            className="w-7 h-7 flex items-center justify-center rounded-md text-gray-400 hover:text-white hover:bg-gray-700 transition-colors text-sm"
          >
            ←
          </button>
          <span className="text-sm font-semibold text-white font-mono tracking-wide">
            {formatDisplayDate(selectedDate)}
          </span>
          <button
            onClick={() => navigateDay(1)}
            className="w-7 h-7 flex items-center justify-center rounded-md text-gray-400 hover:text-white hover:bg-gray-700 transition-colors text-sm"
          >
            →
          </button>
        </div>

        {/* Trade Summary */}
        <div className="flex items-center gap-4">
          {/* Phase Legend */}
          <div className="hidden lg:flex items-center gap-2">
            {Object.entries(PHASE_LABELS).map(([key, label]) => (
              <div key={key} className="flex items-center gap-1">
                <div className="w-2 h-2 rounded-full" style={{ backgroundColor: PHASE_COLORS[key] }} />
                <span className="text-[9px] text-gray-500">{label}</span>
              </div>
            ))}
          </div>

          {tradeSummary ? (
            <div className="flex items-center gap-3 pl-3 border-l border-gray-700">
              <span className="text-xs text-gray-400 uppercase font-medium">
                {tradeSummary.strategy}
              </span>
              <span className={`text-xs font-bold ${tradeSummary.direction === 'LONG' ? 'text-emerald-400' : 'text-red-400'}`}>
                {tradeSummary.direction} {tradeSummary.direction === 'LONG' ? '▲' : '▼'}
              </span>
              <span className={`text-sm font-bold font-mono ${tradeSummary.netPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {tradeSummary.netPnl >= 0 ? '+' : ''}₹{tradeSummary.netPnl?.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
              </span>
            </div>
          ) : (
            <span className="text-xs text-gray-500 italic">No trade</span>
          )}
        </div>
      </div>

      {/* Chart Area */}
      <div className="flex-1 min-h-0 relative">
        {dayLoading ? (
          <div className="absolute inset-0 flex items-center justify-center bg-gray-900/50 z-10">
            <div className="flex items-center gap-3">
              <span className="spinner" />
              <span className="text-sm text-gray-400">Loading chart...</span>
            </div>
          </div>
        ) : !dayData?.candles?.length ? (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center">
              <div className="text-3xl mb-2">📊</div>
              <p className="text-sm text-gray-500">No candle data for this date</p>
            </div>
          </div>
        ) : null}
        <div ref={containerRef} className="w-full h-full" />
      </div>
    </div>
  )
}
