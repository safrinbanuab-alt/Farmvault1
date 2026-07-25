const TYPE_STYLES = {
  info: { dot: 'bg-blue-500', label: 'text-blue-600' },
  warning: { dot: 'bg-amber-500', label: 'text-amber-600' },
  critical: { dot: 'bg-rose-500', label: 'text-rose-600' },
  success: { dot: 'bg-emerald-500', label: 'text-emerald-600' }
}

export default function Timeline({ events = [] }) {
  if (events.length === 0) {
    return <p className="text-sm text-slate-400">No events recorded yet.</p>
  }

  const sorted = [...events].sort(
    (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
  )

  return (
    <ol className="relative space-y-5 border-l border-slate-200 pl-5">
      {sorted.map((event) => {
        const style = TYPE_STYLES[event.type] ?? TYPE_STYLES.info
        return (
          <li key={event.id} className="relative">
            <span
              className={`absolute -left-[26px] top-1 h-3 w-3 rounded-full ring-4 ring-white ${style.dot}`}
            />
            <div className="flex flex-wrap items-baseline justify-between gap-x-3">
              <p className="text-sm font-medium text-slate-800">{event.title}</p>
              <span className="text-xs text-slate-400">{event.timestamp}</span>
            </div>
            {event.description && (
              <p className="mt-0.5 text-sm text-slate-500">{event.description}</p>
            )}
            {event.type && (
              <span className={`mt-1 inline-block text-xs font-medium capitalize ${style.label}`}>
                {event.type}
              </span>
            )}
          </li>
        )
      })}
    </ol>
  )
}