/**
 * Auth Store - Zustand-basiertes State Management für Authentifizierung.
 */

import { create } from 'zustand'
import type { User } from '../types'
import { authApi } from '../services/api'

interface AuthState {
  user: User | null
  token: string | null
  refreshToken: string | null
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  loadFromStorage: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: null,
  refreshToken: null,

  login: async (username, password) => {
    const response = await authApi.login(username, password)
    localStorage.setItem('atlas_token', response.access_token)
    localStorage.setItem('atlas_refresh_token', response.refresh_token)
    localStorage.setItem('atlas_user', JSON.stringify(response.user))
    set({
      user: response.user,
      token: response.access_token,
      refreshToken: response.refresh_token,
    })
  },

  logout: () => {
    localStorage.removeItem('atlas_token')
    localStorage.removeItem('atlas_refresh_token')
    localStorage.removeItem('atlas_user')
    set({ user: null, token: null, refreshToken: null })
  },

  loadFromStorage: () => {
    const token = localStorage.getItem('atlas_token')
    const refreshToken = localStorage.getItem('atlas_refresh_token')
    const userStr = localStorage.getItem('atlas_user')
    if (token && userStr) {
      set({ token, refreshToken, user: JSON.parse(userStr) })
    }
  },
}))
