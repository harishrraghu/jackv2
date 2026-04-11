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

export default api
