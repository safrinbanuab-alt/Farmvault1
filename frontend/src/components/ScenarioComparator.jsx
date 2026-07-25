import { BarChart, Bar, Cell, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'

const COLORS = ['#10b981', '#3b82f6', '#f59e0b', '#f43f5e', '#8b5cf6']

export default function ScenarioComparator({ scenarios = [], results = {} }) {
  const rows = scenarios
    .filter((s) => results[s.id])
    .map((s, idx) => ({
      label: s.label,
      color: COLORS[idx % COLORS.length],
      shelfLife: results[s.id]?.predicted_shelf_life_days ?? 0,
      spoilage: results[s.id]?.spoilage_pct ?? 0,
      valueProtected: results[s.id]?.value_protected ?? 0
    }))

  if (rows.length === 0) {
    return <p className="text-sm text-slate-400">Run the comparison to see results here.</p>
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="h-64">
          <p className="mb-2 text-sm font-medium text-slate-600">Predicted shelf life (days)</p>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} stroke="#94a3b8" />
              <YAxis tick={{ fontSize: 11 }} stroke="#94a3b8" />
              <Tooltip />
              <Bar dataKey="shelfLife" radius={[6, 6, 0, 0]}>
                {rows.map((row) => (
                  <Cell key={row.label} fill={row.color} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="h-64">
          <p className="mb-2 text-sm font-medium text-slate-600">Projected spoilage (%)</p>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} stroke="#94a3b8" />
              <YAxis tick={{ fontSize: 11 }} stroke="#94a3b8" />
              <Tooltip />
              <Bar dataKey="spoilage" fill="#f43f5e" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-slate-400">
              <th className="pb-2 font-medium">Scenario</th>
              <th className="pb-2 font-medium">Shelf life</th>
              <th className="pb-2 font-medium">Spoilage</th>
              <th className="pb-2 font-medium">Value protected</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label} className="border-b border-slate-100 last:border-0">
                <td className="flex items-center gap-2 py-2 text-slate-800">
                  <span className="h-2 w-2 rounded-full" style={{ backgroundColor: row.color }} />
                  {row.label}
                </td>
                <td className="py-2 text-slate-600">{row.shelfLife} d</td>
                <td className="py-2 text-slate-600">{row.spoilage}%</td>
                <td className="py-2 text-slate-600">₹{row.valueProtected}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}