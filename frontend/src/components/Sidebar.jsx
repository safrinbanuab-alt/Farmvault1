import { NavLink } from 'react-router-dom'

const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', end: true, icon: 'grid' },
  { to: '/twin', label: 'Produce twin', icon: 'leaf' },
  { to: '/scenarios', label: 'Scenarios', icon: 'branch' },
  { to: '/analytics', label: 'Analytics', icon: 'chart' }
]

const ICONS = {
  grid: (
    <path strokeLinecap="round" strokeLinejoin="round" d="M4 4h6v6H4V4Zm10 0h6v6h-6V4ZM4 14h6v6H4v-6Zm10 0h6v6h-6v-6Z" />
  ),
  leaf: (
    <path strokeLinecap="round" strokeLinejoin="round" d="M5 21c9 0 14-5 14-14V5h-2C8 5 3 10 3 19v2Zm0 0 9-9" />
  ),
  branch: (
    <path strokeLinecap="round" strokeLinejoin="round" d="M6 3v6a3 3 0 0 0 3 3h6a3 3 0 0 0 3-3V3M6 21v-6M18 21v-6M12 12v9" />
  ),
  chart: (
    <path strokeLinecap="round" strokeLinejoin="round" d="M4 20V10m6 10V4m6 16v-7" />
  )
}

export default function Sidebar() {
  return (
    <aside className="hidden w-56 shrink-0 flex-col border-r border-slate-200 bg-white px-3 py-4 sm:flex">
      <nav className="flex flex-1 flex-col gap-1">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-emerald-50 text-emerald-700'
                  : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
              }`
            }
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
              {ICONS[item.icon]}
            </svg>
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="rounded-lg bg-slate-50 p-3 text-xs text-slate-500">
        <p className="font-medium text-slate-700">Digital twin sim</p>
        <p className="mt-1">IoT + market feeds are simulated for this demo environment.</p>
      </div>
    </aside>
  )
}