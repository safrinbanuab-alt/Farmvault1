import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'

const FRESHNESS_TONE = (score) => {
  if (score == null) return { ring: 'stroke-slate-300', text: 'text-slate-500' }
  if (score >= 70) return { ring: 'stroke-emerald-500', text: 'text-emerald-600' }
  if (score >= 40) return { ring: 'stroke-amber-500', text: 'text-amber-600' }
  return { ring: 'stroke-rose-500', text: 'text-rose-600' }
}

function FreshnessRing({ score }) {
  const clamped = Math.max(0, Math.min(100, score ?? 0))
  const radius = 42
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (clamped / 100) * circumference
  const tone = FRESHNESS_TONE(score)

  return (
    <div className="relative flex h-32 w-32 items-center justify-center">
      <svg viewBox="0 0 100 100" className="h-32 w-32 -rotate-90">
        <circle cx="50" cy="50" r={radius} strokeWidth="8" className="fill-none stroke-slate-100" />
        <circle
          cx="50"
          cy="50"
          r={radius}
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          className={`fill-none transition-all duration-500 ${tone.ring}`}
        />
      </svg>
      <div className="absolute flex flex-col items-center">
        <span className={`text-2xl font-semibold ${tone.text}`}>
          {score != null ? Math.round(score) : '—'}
        </span>
        <span className="text-xs text-slate-400">freshness</span>
      </div>
    </div>
  )
}

function ReadoutTile({ label, value, unit }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
      <p className="text-xs text-slate-400">{label}</p>
      <p className="text-lg font-semibold text-slate-800">
        {value != null ? value : '—'}
        {value != null && unit ? <span className="ml-1 text-xs font-normal text-slate-400">{unit}</span> : null}
      </p>
    </div>
  )
}

export default function TwinVisualizer({ twin, sensorHistory = [] }) {
  const latest = sensorHistory[sensorHistory.length - 1] ?? {}

  return (
    <div className="space-y-5">
      <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-center sm:justify-around">
        <FreshnessRing score={twin?.freshness_score} />
        <div className="grid w-full grid-cols-2 gap-3 sm:w-auto">
          <ReadoutTile label="Temperature" value={latest.temperature ?? twin?.current_temp} unit="°C" />
          <ReadoutTile label="Humidity" value={latest.humidity ?? twin?.current_humidity} unit="%" />
          <ReadoutTile label="Ethylene" value={latest.ethylene_ppm} unit="ppm" />
          <ReadoutTile label="Days tracked" value={twin?.days_in_storage} unit="d" />
        </div>
      </div>

      <div className="h-48">
        {sensorHistory.length > 0 ? (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={sensorHistory} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="timestamp" tick={{ fontSize: 11 }} stroke="#94a3b8" />
              <YAxis tick={{ fontSize: 11 }} stroke="#94a3b8" />
              <Tooltip />
              <Line type="monotone" dataKey="temperature" stroke="#10b981" dot={false} strokeWidth={2} />
              <Line type="monotone" dataKey="humidity" stroke="#3b82f6" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-slate-400">
            Waiting for sensor data…
          </div>
        )}
      </div>
    </div>
  )
}