/**
 * MainLayout - Hauptlayout mit Sidebar-Navigation.
 */

import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { useAuthStore } from '../../stores/authStore'

export default function MainLayout() {
  const { user, logout } = useAuthStore()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const navItems = [
    { to: '/chat', label: 'Chat' },
    { to: '/context', label: 'Kontext' },
    { to: '/documents', label: 'Dokumente' },
    ...(user?.is_admin ? [{ to: '/admin', label: 'Admin' }] : []),
  ]

  return (
    <div className="flex h-screen">
      {/* Navigation Sidebar */}
      <nav className="w-16 bg-atlas-800 flex flex-col items-center py-4 gap-4">
        <div className="text-white font-bold text-lg mb-4">A</div>
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `w-10 h-10 rounded-lg flex items-center justify-center text-xs font-medium transition ${
                isActive ? 'bg-white text-atlas-800' : 'text-white/70 hover:bg-white/10'
              }`
            }
            title={item.label}
          >
            {item.label.charAt(0)}
          </NavLink>
        ))}
        <div className="mt-auto">
          <button
            onClick={handleLogout}
            className="w-10 h-10 rounded-lg flex items-center justify-center text-white/70 hover:bg-white/10 text-xs"
            title="Abmelden"
          >
            X
          </button>
        </div>
      </nav>

      {/* Hauptinhalt */}
      <main className="flex-1 overflow-hidden bg-gray-50">
        <Outlet />
      </main>
    </div>
  )
}
