const PRIORITY_STYLES = {
  high: 'border-rose-200 bg-rose-50 text-rose-700',
  medium: 'border-amber-200 bg-amber-50 text-amber-700',
  low: 'border-emerald-200 bg-emerald-50 text-emerald-700'
}

export default function RecommendationCard({ recommendation, onAction }) {
  const {
    title,
    description,
    priority = 'medium',
    confidence,
    action_label: actionLabel
  } = recommendation ?? {}

  const priorityStyle = PRIORITY_STYLES[priority] ?? PRIORITY_STYLES.medium

  return (
    <div className="rounded-xl border border-slate-200 p-3">
      <div className="flex items-start justify-between gap-2">
        <h4 className="text-sm font-medium text-slate-800">{title}</h4>
        <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize ${priorityStyle}`}>
          {priority}
        </span>
      </div>

      {description && <p className="mt-1 text-sm text-slate-500">{description}</p>}

      <div className="mt-3 flex items-center justify-between">
        {confidence != null ? (
          <span className="text-xs text-slate-400">{Math.round(confidence * 100)}% confidence</span>
        ) : (
          <span />
        )}
        {actionLabel && (
          <button
            type="button"
            onClick={() => onAction?.(recommendation)}
            className="rounded-lg bg-emerald-600 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-700"
          >
            {actionLabel}
          </button>
        )}
      </div>
    </div>
  )
}