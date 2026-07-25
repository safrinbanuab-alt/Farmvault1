import { useRef, useState } from 'react'
import { injectAnomaly } from '../services/api.js'

const ANOMALY_TYPES = [
  { value: 'temperature_spike', label: 'Temperature spike' },
  { value: 'humidity_drop', label: 'Humidity drop' },
  { value: 'sensor_failure', label: 'Sensor failure' },
  { value: 'delayed_shipment', label: 'Delayed shipment' }
]

export default function InjectAnomalyButton({ produceId }) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [feedback, setFeedback] = useState(null)
  const closeTimer = useRef(null)

  async function handleSelect(type) {
    setOpen(false)
    setLoading(true)
    setFeedback(null)
    try {
      await injectAnomaly(produceId, type)
      setFeedback({ tone: 'success', text: `Injected: ${type.replaceAll('_', ' ')}` })
    } catch (err) {
      setFeedback({ tone: 'error', text: err.message || 'Injection failed' })
    } finally {
      setLoading(false)
      clearTimeout(closeTimer.current)
      closeTimer.current = setTimeout(() => setFeedback(null), 4000)
    }
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        disabled={!produceId || loading}
        className="inline-flex items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-1.5 text-sm font-medium text-amber-700 hover:bg-amber-100 disabled:opacity-50"
      >
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v4m0 4h.01M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
        </svg>
        {loading ? 'Injecting…' : 'Inject anomaly'}
      </button>

      {open && (
        <div className="absolute right-0 z-10 mt-2 w-52 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg">
          {ANOMALY_TYPES.map((type) => (
            <button
              key={type.value}
              type="button"
              onClick={() => handleSelect(type.value)}
              className="block w-full px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50"
            >
              {type.label}
            </button>
          ))}
        </div>
      )}

      {feedback && (
        <p
          className={`absolute right-0 mt-2 w-52 text-xs ${
            feedback.tone === 'success' ? 'text-emerald-600' : 'text-rose-600'
          }`}
        >
          {feedback.text}
        </p>
      )}
    </div>
  )
}