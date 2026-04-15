import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 120000,
})

export const fetchDays = (split) => api.get(`/days/${split}`).then(r => r.data)
export const fetchDay = (split, date) => api.get(`/day/${split}/${date}`).then(r => r.data)
export const fetchEquity = (split) => api.get(`/equity/${split}`).then(r => r.data)
export const fetchMetrics = (split) => api.get(`/metrics/${split}`).then(r => r.data)
export const fetchShortcomings = (split) => api.get(`/shortcomings/${split}`).then(r => r.data)
export const runSimulation = (split) => api.post(`/run/${split}`).then(r => r.data)

// Live trading endpoints
export const fetchLiveStatus = () => api.get('/live/status').then(r => r.data)
export const fetchPositions = () => api.get('/live/positions').then(r => r.data)
export const fetchFunds = () => api.get('/live/funds').then(r => r.data)
export const fetchLivePrice = (symbol) => api.get(`/live/price/${symbol}`).then(r => r.data)
export const fetchOptionChain = (symbol) => api.get(`/live/option-chain/${symbol}`).then(r => r.data)

// Knowledge base endpoints
export const fetchKBStrategies = () => api.get('/kb/strategies').then(r => r.data)
export const fetchKBBehaviors = () => api.get('/kb/behaviors').then(r => r.data)
export const fetchKBRisk = () => api.get('/kb/risk').then(r => r.data)
export const fetchKBPerformance = (days = 30) => api.get(`/kb/performance?days=${days}`).then(r => r.data)
export const fetchDiscoveries = () => api.get('/kb/discoveries').then(r => r.data)

// Inbox / messaging
export const fetchInbox = (agent) => api.get(`/inbox/${agent}`).then(r => r.data)
export const sendMessage = (data) => api.post('/inbox/send', data).then(r => r.data)

// Time machine
export const runTimeMachine = (data) => api.post('/timemachine/run', data, { timeout: 600000 }).then(r => r.data)
export const fetchReplayResults = (start, end) => api.get(`/timemachine/results/${start}/${end}`).then(r => r.data)
export const replaySingleDay = (date) => api.get(`/timemachine/replay-day/${date}`, { timeout: 300000 }).then(r => r.data)

// Full day agent simulation
export const simulateDay = (data) => api.post('/simulate-day', data, { timeout: 300000 }).then(r => r.data)

export default api
