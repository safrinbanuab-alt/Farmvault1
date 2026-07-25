import { useEffect, useState } from 'react'
import PriceChart from '../components/PriceChart.jsx'
import DecayChart from '../components/DecayChart.jsx'
import { getAnalytics } from '../services/api.js'

const RANGE_OPTIONS = [
  { value: '7d', label: '7 days' },
  { value: '30d', label: '30 days' },
  { value: '90d', label: '90 days' }
]

function InsightCard({ title, value, delta }) {
  const positive = typeof delta === 'number' && delta >= 0
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-400">{title}</p>
      <p className="mt-1 text-2xl font-semibold text-slate-900">{value}</p>
      {typeof delta === 'number' && (
        <p className={`mt-1 text-xs font-medium ${positive ? 'text-emerald-600' : 'text-rose-600'}`}>
          {positive ? '▲' : '▼'} {Math.abs(delta)}% vs previous period
        </p>
      )}
    </div>
  )
}

export default function Analytics() {
  const [range, setRange] = useState('30d')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    getAnalytics(range)
      .then((res) => {
        if (!cancelled) setData(res)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Failed to load analytics')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [range])

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Analytics</h1>
          <p className="text-sm text-slate-500">Trends across decay, pricing, and losses avoided</p>
        </div>
        <div className="flex overflow-hidden rounded-lg border border-slate-300">
          {RANGE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setRange(opt.value)}
              className={`px-3 py-1.5 text-sm font-medium ${
                range === opt.value
                  ? 'bg-emerald-600 text-white'
                  : 'bg-white text-slate-600 hover:bg-slate-50'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {loading && <div className="text-slate-400">Loading analytics…</div>}

      {error && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-rose-700">{error}</div>
      )}

      {data && (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <InsightCard
              title="Avg. shelf life"
              value={data.avg_shelf_life ?? '—'}
              delta={data.shelf_life_delta}
            />
            <InsightCard
              title="Spoilage rate"
              value={data.spoilage_rate ?? '—'}
              delta={data.spoilage_delta}
            />
            <InsightCard
              title="Avg. mandi price"
              value={data.avg_price ?? '—'}
              delta={data.price_delta}
            />
            <InsightCard
              title="Value protected"
              value={data.value_protected ?? '—'}
              delta={data.value_delta}
            />
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div className="rounded-2xl border border-slate-200 bg-white p-4">
              <h2 className="mb-3 text-lg font-medium text-slate-800">Price trend</h2>
              <PriceChart data={data.price_history ?? []} />
            </div>
            <div className="rounded-2xl border border-slate-200 bg-white p-4">
              <h2 className="mb-3 text-lg font-medium text-slate-800">Decay trend</h2>
              <DecayChart data={data.decay_history ?? []} />
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-4">
            <h2 className="mb-3 text-lg font-medium text-slate-800">Top produce by risk</h2>
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-slate-400">
                  <th className="pb-2 font-medium">Produce</th>
                  <th className="pb-2 font-medium">Risk score</th>
                  <th className="pb-2 font-medium">Days to spoilage</th>
                  <th className="pb-2 font-medium">Recommended action</th>
                </tr>
              </thead>
              <tbody>
                {(data.top_risk ?? []).map((row) => (
                  <tr key={row.produce_id} className="border-b border-slate-100 last:border-0">
                    <td className="py-2 text-slate-800">{row.name}</td>
                    <td className="py-2 text-slate-600">{row.risk_score}</td>
                    <td className="py-2 text-slate-600">{row.days_to_spoilage}</td>
                    <td className="py-2 text-slate-600">{row.recommended_action}</td>
                  </tr>
                ))}
                {(data.top_risk ?? []).length === 0 && (
                  <tr>
                    <td colSpan={4} className="py-4 text-center text-slate-400">
                      No at-risk produce right now.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}