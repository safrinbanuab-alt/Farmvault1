import { LineChart, Line, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, CartesianGrid } from 'recharts'

function normalize(data, decayCurve) {
  const actual = data.map((point) => ({
    timestamp: point.timestamp,
    actual: point.freshness_score ?? point.decay_pct ?? null
  }))

  if (!decayCurve || decayCurve.length === 0) return actual

  const merged = [...actual]
  decayCurve.forEach((point, idx) => {
    if (merged[idx]) {
      merged[idx].predicted = point.predicted_freshness ?? point.value
    } else {
      merged.push({
        timestamp: point.timestamp ?? `day ${idx}`,
        predicted: point.predicted_freshness ?? point.value
      })
    }
  })
  return merged
}

export default function DecayChart({ data = [], decayCurve = [], height = 240 }) {
  const chartData = normalize(data, decayCurve)

  if (chartData.length === 0) {
    return (
      <div className="flex items-center justify-center text-sm text-slate-400" style={{ height }}>
        No decay data yet
      </div>
    )
  }

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="timestamp" tick={{ fontSize: 11 }} stroke="#94a3b8" />
          <YAxis tick={{ fontSize: 11 }} stroke="#94a3b8" domain={[0, 100]} />
          <Tooltip contentStyle={{ borderRadius: 8, borderColor: '#e2e8f0', fontSize: 12 }} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Line
            type="monotone"
            dataKey="actual"
            name="Actual freshness"
            stroke="#10b981"
            strokeWidth={2}
            dot={false}
            connectNulls
          />
          <Line
            type="monotone"
            dataKey="predicted"
            name="Predicted decay"
            stroke="#f59e0b"
            strokeWidth={2}
            strokeDasharray="5 4"
            dot={false}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}