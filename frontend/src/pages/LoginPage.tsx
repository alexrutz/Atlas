import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../stores/authStore'

export default function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const login = useAuthStore((s) => s.login)
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(username, password)
      navigate('/chat')
    } catch {
      setError('Ungültige Anmeldedaten')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-100">
      <div className="bg-white p-8 rounded-lg shadow-md w-full max-w-md">
        <h1 className="text-2xl font-bold text-center text-atlas-700 mb-6">Atlas</h1>
        <p className="text-gray-500 text-center mb-6">Firmen-Wissensdatenbank</p>
        <form onSubmit={handleSubmit} className="space-y-4">
          {error && <div className="bg-red-50 text-red-600 p-3 rounded text-sm">{error}</div>}
          <input
            type="text" placeholder="Benutzername" value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="w-full p-3 border rounded focus:ring-2 focus:ring-atlas-500 outline-none"
            required
          />
          <input
            type="password" placeholder="Passwort" value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full p-3 border rounded focus:ring-2 focus:ring-atlas-500 outline-none"
            required
          />
          <button
            type="submit" disabled={loading}
            className="w-full bg-atlas-600 text-white p-3 rounded hover:bg-atlas-700 disabled:opacity-50 transition"
          >
            {loading ? 'Anmelden...' : 'Anmelden'}
          </button>
        </form>
      </div>
    </div>
  )
}
