import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import ProduceCard from '../components/ProduceCard.jsx'
import MarketCard from '../components/MarketCard.jsx'
import AlertPanel from '../components/AlertPanel.jsx'
import PriceChart from '../components/PriceChart.jsx'
import { getDashboardSummary } from '../services/api.js'

function StatPill({ label, value, tone = 'emerald' }) {
  const tones = {
    emerald: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    amber: 'bg-amber-50 text-amber-700 border-amber-200',
    rose: 'bg-rose-50 text-rose-700 border-rose-200',
    slate: 'bg-slate-100 text-slate-700 border-slate-200'
  }
  return (
    <div className={`rounded-xl border px-4 py-3 ${tones[tone]}`}>
      <p className="text-xs font-medium uppercase tracking-wide opacity-70">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
    </div>
  )
}

export default function Dashboard() {
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    getDashboardSummary()
      .then((data) => {
        if (!cancelled) setSummary(data)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Failed to load dashboard')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (loading) {
    return <div className="text-slate-400">Loading dashboard…</div>
  }

  if (error) {
    return (
      <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-rose-700">
        Couldn't load the dashboard: {error}
      </div>
    )
  }

  const produce = summary?.produce ?? []
  const markets = summary?.markets ?? []
  const alerts = summary?.alerts ?? []
  const priceHistory = summary?.price_history ?? []

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Dashboard</h1>
        <p className="text-sm text-slate-500">Live overview of produce, markets, and alerts</p>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatPill label="Produce lots" value={summary?.total_produce ?? produce.length} />
        <StatPill label="Active alerts" value={summary?.active_alerts ?? alerts.length} tone="rose" />
        <StatPill label="Markets tracked" value={summary?.tracked_markets ?? markets.length} tone="slate" />
        <StatPill label="Est. value saved" value={summary?.value_saved ?? '—'} tone="amber" />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2 rounded-2xl border border-slate-200 bg-white p-4">
          <h2 className="mb-3 text-lg font-medium text-slate-800">Market price trend</h2>
          <PriceChart data={priceHistory} />
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-4">
          <h2 className="mb-3 text-lg font-medium text-slate-800">Alerts</h2>
          <AlertPanel alerts={alerts} />
        </div>
      </div>

      <div>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-medium text-slate-800">Produce twins</h2>
          <Link to="/twin" className="text-sm font-medium text-emerald-600 hover:text-emerald-700">
            View all →
          </Link>
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {produce.map((item) => (
            <Link key={item.id} to={`/twin/${item.id}`}>
              <ProduceCard produce={item} />
            </Link>
          ))}
          {produce.length === 0 && (
            <p className="text-sm text-slate-400">No produce lots yet.</p>
          )}
        </div>
      </div>

      <div>
        <h2 className="mb-3 text-lg font-medium text-slate-800">Markets</h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {markets.map((market) => (
            <MarketCard key={market.id} market={market} />
          ))}
          {markets.length === 0 && (
            <p className="text-sm text-slate-400">No market feeds yet.</p>
          )}
        </div>
      </div>
    </div>
  )
}