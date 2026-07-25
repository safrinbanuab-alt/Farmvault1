import { useState } from 'react'

const SEVERITY_STYLES = {
  critical: { dot: 'bg-rose-500', badge: 'border-rose-200 bg-rose-50 text-rose-700' },
  warning: { dot: 'bg-amber-500', badge: 'border-amber-200 bg-amber-50 text-amber-700' },
  info: { dot: 'bg-blue-500', badge: 'border-blue-200 bg-blue-50 text-blue-700' }
}

export default function AlertPanel({ alerts = [], onDismiss }) {
  const [dismissed, setDismissed] = useState(new Set())

  function handleDismiss(id) {
    setDismissed((prev) => new Set(prev).add(id))
    onDismiss?.(id)
  }

  const visible = alerts.filter((alert) => !dismissed.has(alert.id))

  if (visible.length === 0) {
    return (
      <div className="flex h-full min-h-[120px] items-center justify-center text-sm text-slate-400">
        No active alerts
      </div>
    )
  }

  return (
    <ul className="space-y-3">
      {visible.map((alert) => {
        const style = SEVERITY_STYLES[alert.severity] ?? SEVERITY_STYLES.info
        return (
          <li key={alert.id} className="flex items-start gap-3 rounded-xl border border-slate-100 p-3">
            <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${style.dot}`} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center justify-between gap-x-2">
                <p className="text-sm font-medium text-slate-800">{alert.title}</p>
                <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize ${style.badge}`}>
                  {alert.severity}
                </span>
              </div>
              {alert.message && <p className="mt-0.5 text-xs text-slate-500">{alert.message}</p>}
              {alert.timestamp && <p className="mt-1 text-[11px] text-slate-400">{alert.timestamp}</p>}
            </div>
            <button
              type="button"
              aria-label="Dismiss alert"
              onClick={() => handleDismiss(alert.id)}
              className="shrink-0 rounded p-1 text-slate-300 hover:bg-slate-100 hover:text-slate-500"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          </li>
        )
      })}
    </ul>
  )
}