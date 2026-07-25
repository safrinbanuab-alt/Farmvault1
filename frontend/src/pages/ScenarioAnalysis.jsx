import { useEffect, useState } from 'react'
import ScenarioComparator from '../components/ScenarioComparator.jsx'
import { getProduceList, runSimulation } from '../services/api.js'

const DEFAULT_SCENARIO = {
  produceId: '',
  storageTemp: 4,
  storageHumidity: 85,
  holdDays: 5,
  transportMode: 'refrigerated'
}

export default function ScenarioAnalysis() {
  const [produceOptions, setProduceOptions] = useState([])
  const [scenarios, setScenarios] = useState([{ ...DEFAULT_SCENARIO, id: 'a', label: 'Scenario A' }])
  const [results, setResults] = useState({})
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    getProduceList()
      .then(setProduceOptions)
      .catch(() => setProduceOptions([]))
  }, [])

  function updateScenario(id, patch) {
    setScenarios((prev) => prev.map((s) => (s.id === id ? { ...s, ...patch } : s)))
  }

  function addScenario() {
    const nextLabel = String.fromCharCode(65 + scenarios.length)
    setScenarios((prev) => [
      ...prev,
      { ...DEFAULT_SCENARIO, id: crypto.randomUUID(), label: `Scenario ${nextLabel}` }
    ])
  }

  function removeScenario(id) {
    setScenarios((prev) => prev.filter((s) => s.id !== id))
    setResults((prev) => {
      const next = { ...prev }
      delete next[id]
      return next
    })
  }

  async function runAll() {
    setRunning(true)
    setError(null)
    try {
      const entries = await Promise.all(
        scenarios.map(async (scenario) => {
          const result = await runSimulation({
            produce_id: scenario.produceId,
            storage_temp: scenario.storageTemp,
            storage_humidity: scenario.storageHumidity,
            hold_days: scenario.holdDays,
            transport_mode: scenario.transportMode
          })
          return [scenario.id, result]
        })
      )
      setResults(Object.fromEntries(entries))
    } catch (err) {
      setError(err.message || 'Simulation failed')
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Scenario analysis</h1>
          <p className="text-sm text-slate-500">
            Compare storage and transport choices before committing produce to a plan
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={addScenario}
            className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            + Add scenario
          </button>
          <button
            onClick={runAll}
            disabled={running || scenarios.length === 0}
            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
          >
            {running ? 'Running…' : 'Run comparison'}
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-rose-700">{error}</div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {scenarios.map((scenario) => (
          <div key={scenario.id} className="rounded-2xl border border-slate-200 bg-white p-4">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="font-medium text-slate-800">{scenario.label}</h3>
              {scenarios.length > 1 && (
                <button
                  onClick={() => removeScenario(scenario.id)}
                  className="text-xs text-slate-400 hover:text-rose-600"
                >
                  Remove
                </button>
              )}
            </div>
            <div className="space-y-3 text-sm">
              <label className="block">
                <span className="text-slate-500">Produce lot</span>
                <select
                  value={scenario.produceId}
                  onChange={(e) => updateScenario(scenario.id, { produceId: e.target.value })}
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                >
                  <option value="">Select produce</option>
                  {produceOptions.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="text-slate-500">Storage temp (°C)</span>
                <input
                  type="number"
                  value={scenario.storageTemp}
                  onChange={(e) =>
                    updateScenario(scenario.id, { storageTemp: Number(e.target.value) })
                  }
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                />
              </label>
              <label className="block">
                <span className="text-slate-500">Storage humidity (%)</span>
                <input
                  type="number"
                  value={scenario.storageHumidity}
                  onChange={(e) =>
                    updateScenario(scenario.id, { storageHumidity: Number(e.target.value) })
                  }
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                />
              </label>
              <label className="block">
                <span className="text-slate-500">Hold time (days)</span>
                <input
                  type="number"
                  value={scenario.holdDays}
                  onChange={(e) => updateScenario(scenario.id, { holdDays: Number(e.target.value) })}
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                />
              </label>
              <label className="block">
                <span className="text-slate-500">Transport mode</span>
                <select
                  value={scenario.transportMode}
                  onChange={(e) => updateScenario(scenario.id, { transportMode: e.target.value })}
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                >
                  <option value="refrigerated">Refrigerated</option>
                  <option value="ambient">Ambient</option>
                  <option value="controlled_atmosphere">Controlled atmosphere</option>
                </select>
              </label>
            </div>
          </div>
        ))}
      </div>

      {Object.keys(results).length > 0 && (
        <div className="rounded-2xl border border-slate-200 bg-white p-4">
          <h2 className="mb-3 text-lg font-medium text-slate-800">Comparison</h2>
          <ScenarioComparator scenarios={scenarios} results={results} />
        </div>
      )}
    </div>
  )
}