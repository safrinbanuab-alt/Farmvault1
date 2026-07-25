import { useParams, Link } from 'react-router-dom'
import TwinVisualizer from '../components/TwinVisualizer.jsx'
import DecayChart from '../components/DecayChart.jsx'
import Timeline from '../components/Timeline.jsx'
import RecommendationCard from '../components/RecommendationCard.jsx'
import InjectAnomalyButton from '../components/InjectAnomalyButton.jsx'
import useTwinData from '../hooks/useTwinData.js'

export default function ProduceTwin() {
  const { produceId } = useParams()
  const { twin, sensorHistory, recommendations, timelineEvents, connected, loading, error } =
    useTwinData(produceId)

  if (!produceId) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-center text-slate-500">
        Select a produce lot from the dashboard to open its digital twin.
      </div>
    )
  }

  if (loading) {
    return <div className="text-slate-400">Connecting to twin…</div>
  }

  if (error) {
    return (
      <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-rose-700">
        Couldn't load this twin: {error}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link to="/" className="text-sm text-slate-400 hover:text-slate-600">
            ← Back to dashboard
          </Link>
          <h1 className="mt-1 text-2xl font-semibold text-slate-900">
            {twin?.name ?? `Produce twin ${produceId}`}
          </h1>
          <p className="text-sm text-slate-500">
            {twin?.variety} · {twin?.location ?? 'Unknown location'}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span
            className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium ${
              connected
                ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                : 'border-slate-200 bg-slate-100 text-slate-500'
            }`}
          >
            <span
              className={`h-2 w-2 rounded-full ${connected ? 'bg-emerald-500' : 'bg-slate-400'}`}
            />
            {connected ? 'Live' : 'Offline'}
          </span>
          <InjectAnomalyButton produceId={produceId} />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2 rounded-2xl border border-slate-200 bg-white p-4">
          <h2 className="mb-3 text-lg font-medium text-slate-800">Twin state</h2>
          <TwinVisualizer twin={twin} sensorHistory={sensorHistory} />
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-4">
          <h2 className="mb-3 text-lg font-medium text-slate-800">Recommendations</h2>
          <div className="space-y-3">
            {recommendations.map((rec) => (
              <RecommendationCard key={rec.id} recommendation={rec} />
            ))}
            {recommendations.length === 0 && (
              <p className="text-sm text-slate-400">No recommendations right now.</p>
            )}
          </div>
        </div>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-4">
        <h2 className="mb-3 text-lg font-medium text-slate-800">Decay projection</h2>
        <DecayChart data={sensorHistory} decayCurve={twin?.decay_curve} />
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-4">
        <h2 className="mb-3 text-lg font-medium text-slate-800">Event timeline</h2>
        <Timeline events={timelineEvents} />
      </div>
    </div>
  )
}