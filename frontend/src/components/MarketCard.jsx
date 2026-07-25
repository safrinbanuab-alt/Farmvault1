function TrendBadge({ changePct }) {
  if (changePct == null) {
    return <span className="text-xs font-medium text-slate-400">—</span>
  }
  const up = changePct >= 0
  return (
    <span
      className={`inline-flex items-center gap-1 text-xs font-medium ${
        up ? 'text-emerald-600' : 'text-rose-600'
      }`}
    >
      {up ? '▲' : '▼'} {Math.abs(changePct)}%
    </span>
  )
}

export default function MarketCard({ market }) {
  const {
    name,
    location,
    current_price: currentPrice,
    unit,
    change_pct: changePct,
    updated_at: updatedAt
  } = market ?? {}

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 transition-shadow hover:shadow-md">
      <div className="flex items-start justify-between">
        <div>
          <h3 className="font-medium text-slate-900">{name ?? 'Unnamed mandi'}</h3>
          <p className="text-xs text-slate-500">{location ?? 'Unknown location'}</p>
        </div>
        <TrendBadge changePct={changePct} />
      </div>

      <div className="mt-4 flex items-baseline gap-1">
        <span className="text-2xl font-semibold text-slate-900">
          {currentPrice != null ? `₹${currentPrice}` : '—'}
        </span>
        {unit && <span className="text-xs text-slate-500">/ {unit}</span>}
      </div>

      <p className="mt-2 text-xs text-slate-400">
        {updatedAt ? `Updated ${updatedAt}` : 'No recent updates'}
      </p>
    </div>
  )
}