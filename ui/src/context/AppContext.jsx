import React, { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { fetchDays, fetchDay, fetchEquity, fetchMetrics, fetchShortcomings, runSimulation } from '../api/client'

const AppContext = createContext(null)

export function AppProvider({ children }) {
  const [split, setSplit] = useState('train')
  const [days, setDays] = useState([])
  const [selectedDate, setSelectedDate] = useState(null)
  const [dayData, setDayData] = useState(null)
  const [equity, setEquity] = useState(null)
  const [metrics, setMetrics] = useState(null)
  const [shortcomings, setShortcomings] = useState(null)
  const [loading, setLoading] = useState(false)
  const [dayLoading, setDayLoading] = useState(false)
  const [runStatus, setRunStatus] = useState(null)
  const [error, setError] = useState(null)

  // Load split data
  const loadSplitData = useCallback(async (s) => {
    setLoading(true)
    setError(null)
    try {
      const [daysData, equityData, metricsData, shortData] = await Promise.all([
        fetchDays(s),
        fetchEquity(s),
        fetchMetrics(s),
        fetchShortcomings(s),
      ])
      setDays(daysData)
      setEquity(equityData)
      setMetrics(metricsData)
      setShortcomings(shortData)

      // Select first trading day with a trade, or first day
      const firstTradeDay = daysData.find(d => d.has_trade) || daysData[0]
      if (firstTradeDay) {
        setSelectedDate(firstTradeDay.date)
      }
    } catch (err) {
      console.error('Failed to load split data:', err)
      setError(err.message || 'Failed to load data')
    } finally {
      setLoading(false)
    }
  }, [])

  // Load day data
  const loadDayData = useCallback(async (date) => {
    if (!date) return
    setDayLoading(true)
    try {
      const data = await fetchDay(split, date)
      setDayData(data)
    } catch (err) {
      console.error('Failed to load day data:', err)
    } finally {
      setDayLoading(false)
    }
  }, [split])

  // On split change
  useEffect(() => {
    loadSplitData(split)
  }, [split, loadSplitData])

  // On date change
  useEffect(() => {
    if (selectedDate) {
      loadDayData(selectedDate)
    }
  }, [selectedDate, loadDayData])

  // Navigate to adjacent day
  const navigateDay = useCallback((direction) => {
    if (!days.length || !selectedDate) return
    const idx = days.findIndex(d => d.date === selectedDate)
    if (idx === -1) return
    const newIdx = idx + direction
    if (newIdx >= 0 && newIdx < days.length) {
      setSelectedDate(days[newIdx].date)
    }
  }, [days, selectedDate])

  // Cycle split
  const cycleSplit = useCallback(() => {
    const splits = ['train', 'test', 'holdout']
    const idx = splits.indexOf(split)
    setSplit(splits[(idx + 1) % splits.length])
  }, [split])

  // Run simulation
  const triggerRun = useCallback(async () => {
    setRunStatus('running')
    try {
      const result = await runSimulation(split)
      setRunStatus(result.status === 'ok' ? 'done' : 'error')
      if (result.status === 'ok') {
        // Reload data after successful run
        await loadSplitData(split)
      }
    } catch (err) {
      setRunStatus('error')
    } finally {
      setTimeout(() => setRunStatus(null), 3000)
    }
  }, [split, loadSplitData])

  // Keyboard shortcuts
  useEffect(() => {
    const handleKey = (e) => {
      // Don't capture if user is in input field
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return

      switch (e.key) {
        case 'ArrowLeft':
          e.preventDefault()
          navigateDay(-1)
          break
        case 'ArrowRight':
          e.preventDefault()
          navigateDay(1)
          break
        case 't':
        case 'T':
          cycleSplit()
          break
        case 'r':
        case 'R':
          if (runStatus !== 'running') triggerRun()
          break
      }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [navigateDay, cycleSplit, triggerRun, runStatus])

  const value = {
    split, setSplit,
    days, setDays,
    selectedDate, setSelectedDate,
    dayData, setDayData,
    equity, setEquity,
    metrics, setMetrics,
    shortcomings, setShortcomings,
    loading, dayLoading,
    runStatus, triggerRun,
    navigateDay, cycleSplit,
    error,
  }

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export function useApp() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used within AppProvider')
  return ctx
}
