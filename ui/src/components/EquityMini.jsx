import React, { useEffect, useRef } from 'react'
import { createChart } from 'lightweight-charts'
import { useApp } from '../context/AppContext'

export default function EquityMini() {
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const { equity, selectedDate } = useApp()

  useEffect(() => {
    if (!containerRef.current || !equity?.curve?.length) return

    // Dispose previous chart
    if (chartRef.current) {
      chartRef.current.remove()
      chartRef.current = null
    }

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 70,
      layout: {
        background: { color: 'transparent' },
        textColor: '#6b7280',
        fontSize: 9,
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { visible: false },
      },
      rightPriceScale: {
        visible: false,
      },
      timeScale: {
        visible: false,
      },
      crosshair: {
        vertLine: { visible: false },
        horzLine: { visible: false },
      },
      handleScroll: false,
      handleScale: false,
    })

    const areaSeries = chart.addAreaSeries({
      topColor: 'rgba(16, 185, 129, 0.3)',
      bottomColor: 'rgba(16, 185, 129, 0.02)',
      lineColor: '#10b981',
      lineWidth: 1.5,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    // Deduplicate dates (take last value per date)
    const dateMap = new Map()
    for (const point of equity.curve) {
      dateMap.set(point.date, point.capital)
    }

    const data = Array.from(dateMap.entries()).map(([date, capital]) => ({
      time: date,
      value: capital,
    }))

    areaSeries.setData(data)
    chart.timeScale().fitContent()
    chartRef.current = chart

    return () => {
      if (chartRef.current) {
        chartRef.current.remove()
        chartRef.current = null
      }
    }
  }, [equity])

  return (
    <div ref={containerRef} className="w-full rounded overflow-hidden" style={{ height: '70px' }} />
  )
}
