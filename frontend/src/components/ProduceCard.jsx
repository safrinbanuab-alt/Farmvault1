const FRESHNESS_TONE = (score) => {
  if (score == null) return 'bg-slate-300'
  if (score >= 70) return 'bg-emerald-500'
  if (score >= 40) return 'bg-amber-500'
  return 'bg-rose-500'
}

export default function ProduceCard({ produce }) {
  const {
    name,
    variety,
    quantity_kg: quantityKg,
    freshness_score: freshnessScore,
    days_to_spoilage: daysToSpoilage,
    storage_temp: storageTemp
  } = produce ?? {}

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 transition-shadow hover:shadow-md">
      <div className="flex items-start justify-between">
        <div>
          <h3 className="font-medium text-slate-900">{name ?? 'Unnamed lot'}</h3>
          <p className="text-xs text-slate-500">{variety ?? 'Unknown variety'}</p>
        </div>
        {daysToSpoilage != null && (
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
            {daysToSpoilage}d left
          </span>
        )}
      </div>

      <div className="mt-4">
        <div className="mb-1 flex items-center justify-between text-xs text-slate-500">
          <span>Freshness</span>
          <span>{freshnessScore != null ? `${freshnessScore}%` : '—'}</span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
          <div
            className={`h-full rounded-full ${FRESHNESS_TONE(freshnessScore)}`}
            style={{ width: `${Math.max(0, Math.min(100, freshnessScore ?? 0))}%` }}
          />
        </div>
      </div>

      <div className="mt-4 flex items-center justify-between text-xs text-slate-500">
        <span>{quantityKg != null ? `${quantityKg} kg` : '—'}</span>
        <span>{storageTemp != null ? `${storageTemp}°C storage` : '—'}</span>
      </div>
    </div>
  )
}