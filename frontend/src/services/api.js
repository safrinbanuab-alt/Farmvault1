import axios from 'axios'

// Vite's dev server proxies /api -> http://localhost:8000 (see vite.config.js),
// so relative paths work in both dev and production builds behind the same origin.
const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 15000
})

client.interceptors.response.use(
  (res) => res,
  (err) => {
    const message =
      err.response?.data?.detail || err.response?.data?.message || err.message || 'Request failed'
    return Promise.reject(new Error(message))
  }
)

// ---- dashboard_routes.py ----
export async function getDashboardSummary() {
  const { data } = await client.get('dashboard/overview')
  return data
}

export async function getAnalytics(range = '30d') {
  const { data } = await client.get('/dashboard/analytics', { params: { range } })
  return data
}

// ---- patient_routes.py (produce lots) ----
export async function getProduceList() {
  const { data } = await client.get('/produce')
  return data
}

export async function getProduce(produceId) {
  const { data } = await client.get(`/produce/${produceId}`)
  return data
}

export async function createProduce(payload) {
  const { data } = await client.post('/produce', payload)
  return data
}

export async function updateProduce(produceId, payload) {
  const { data } = await client.put(`/produce/${produceId}`, payload)
  return data
}

export async function deleteProduce(produceId) {
  const { data } = await client.delete(`/produce/${produceId}`)
  return data
}

// ---- market_routes.py ----
export async function getMarkets() {
  const { data } = await client.get('/market')
  return data
}

export async function getMarket(marketId) {
  const { data } = await client.get(`/market/${marketId}`)
  return data
}

export async function getMarketPriceHistory(marketId, range = '30d') {
  const { data } = await client.get(`/market/${marketId}/history`, { params: { range } })
  return data
}

// ---- twin_routes.py ----
export async function getTwin(produceId) {
  const { data } = await client.get(`/twin/${produceId}`)
  return data
}

export async function getTwinSensorHistory(produceId, range = '24h') {
  const { data } = await client.get(`/twin/${produceId}/history`, { params: { range } })
  return data
}

export async function getTwinTimeline(produceId) {
  const { data } = await client.get(`/twin/${produceId}/timeline`)
  return data
}

export async function injectAnomaly(produceId, anomalyType) {
  const { data } = await client.post(`/twin/${produceId}/anomaly`, { type: anomalyType })
  return data
}

// ---- prediction_routes.py ----
export async function getRecommendations(produceId) {
  const { data } = await client.get(`/predictions/${produceId}/recommendations`)
  return data
}

export async function getDecayForecast(produceId) {
  const { data } = await client.get(`/predictions/${produceId}/decay`)
  return data
}

export async function getPriceForecast(marketId, produceId) {
  const { data } = await client.get(`/predictions/price`, { params: { market_id: marketId, produce_id: produceId } })
  return data
}

// ---- simulation_routes.py ----
export async function runSimulation(payload) {
  const { data } = await client.post('/simulation/run', payload)
  return data
}

export async function getSimulationHistory(produceId) {
  const { data } = await client.get('/simulation/history', { params: { produce_id: produceId } })
  return data
}

export default client