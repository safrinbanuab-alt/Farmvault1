import { Routes, Route } from 'react-router-dom'
import Navbar from './components/Navbar.jsx'
import Sidebar from './components/Sidebar.jsx'
import Dashboard from './pages/Dashboard.jsx'
import ProduceTwin from './pages/ProduceTwin.jsx'
import ScenarioAnalysis from './pages/ScenarioAnalysis.jsx'
import Analytics from './pages/Analytics.jsx'

function App() {
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-slate-50 text-slate-900">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <Navbar />
        <main className="flex-1 overflow-y-auto p-6">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/twin/:produceId" element={<ProduceTwin />} />
            <Route path="/twin" element={<ProduceTwin />} />
            <Route path="/scenarios" element={<ScenarioAnalysis />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route
              path="*"
              element={
                <div className="flex h-full items-center justify-center text-slate-400">
                  Page not found
                </div>
              }
            />
          </Routes>
        </main>
      </div>
    </div>
  )
}

export default App
