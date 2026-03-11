/**
 * Atlas API Client
 *
 * Zentraler HTTP-Client für alle Backend-Kommunikation.
 * Fügt automatisch den JWT-Token zu Requests hinzu.
 */

import axios from 'axios'
import type {
  LoginResponse, Collection, Document, GlossaryEntry,
  Conversation, ChatResponse, Group, UserDetail,
} from '../types'

const api = axios.create({ baseURL: '/api' })

// JWT-Token automatisch hinzufügen
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('atlas_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Bei 401: Token-Refresh versuchen, sonst ausloggen
let isRefreshing = false
let failedQueue: Array<{ resolve: (token: string) => void; reject: (err: unknown) => void }> = []

function processQueue(error: unknown, token: string | null) {
  failedQueue.forEach((p) => {
    if (token) p.resolve(token)
    else p.reject(error)
  })
  failedQueue = []
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config
    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({
            resolve: (token: string) => {
              originalRequest.headers.Authorization = `Bearer ${token}`
              resolve(api(originalRequest))
            },
            reject,
          })
        })
      }
      originalRequest._retry = true
      isRefreshing = true

      const refreshToken = localStorage.getItem('atlas_refresh_token')
      if (refreshToken) {
        try {
          const { data } = await axios.post<LoginResponse>('/api/auth/refresh', { refresh_token: refreshToken })
          localStorage.setItem('atlas_token', data.access_token)
          localStorage.setItem('atlas_refresh_token', data.refresh_token)
          localStorage.setItem('atlas_user', JSON.stringify(data.user))
          processQueue(null, data.access_token)
          originalRequest.headers.Authorization = `Bearer ${data.access_token}`
          return api(originalRequest)
        } catch (refreshError) {
          processQueue(refreshError, null)
          localStorage.removeItem('atlas_token')
          localStorage.removeItem('atlas_refresh_token')
          localStorage.removeItem('atlas_user')
          window.location.href = '/login'
          return Promise.reject(refreshError)
        } finally {
          isRefreshing = false
        }
      }

      localStorage.removeItem('atlas_token')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  },
)

// --- Auth ---
export const authApi = {
  login: (username: string, password: string) =>
    api.post<LoginResponse>('/auth/login', { username, password }).then(r => r.data),
  refresh: (refreshToken: string) =>
    api.post<LoginResponse>('/auth/refresh', { refresh_token: refreshToken }).then(r => r.data),
}

// --- Users (Admin) ---
export const usersApi = {
  list: () => api.get<UserDetail[]>('/users').then(r => r.data),
  create: (data: { username: string; email: string; password: string; full_name: string; is_admin?: boolean }) =>
    api.post<UserDetail>('/users', data).then(r => r.data),
  update: (id: number, data: Record<string, unknown>) => api.put<UserDetail>(`/users/${id}`, data).then(r => r.data),
  delete: (id: number) => api.delete(`/users/${id}`),
}

// --- Groups (Admin) ---
export const groupsApi = {
  list: () => api.get<Group[]>('/groups').then(r => r.data),
  create: (data: { name: string; description?: string }) => api.post('/groups', data).then(r => r.data),
  update: (id: number, data: Record<string, unknown>) => api.put(`/groups/${id}`, data).then(r => r.data),
  delete: (id: number) => api.delete(`/groups/${id}`),
  addMembers: (groupId: number, userIds: number[]) =>
    api.post(`/groups/${groupId}/members`, { user_ids: userIds }),
  removeMember: (groupId: number, userId: number) =>
    api.delete(`/groups/${groupId}/members/${userId}`),
}

// --- Collections ---
export const collectionsApi = {
  list: () => api.get<Collection[]>('/collections').then(r => r.data),
  create: (data: { name: string; description?: string }) => api.post('/collections', data).then(r => r.data),
  update: (id: number, data: Record<string, unknown>) => api.put(`/collections/${id}`, data).then(r => r.data),
  delete: (id: number) => api.delete(`/collections/${id}`),
  setAccess: (collectionId: number, groupId: number, canRead: boolean, canWrite: boolean) =>
    api.post(`/collections/${collectionId}/access`, { group_id: groupId, can_read: canRead, can_write: canWrite }),
  getGlossary: (collectionId: number) =>
    api.get<GlossaryEntry[]>(`/collections/${collectionId}/glossary`).then(r => r.data),
  addGlossaryEntry: (collectionId: number, data: { term: string; definition: string; abbreviation?: string }) =>
    api.post(`/collections/${collectionId}/glossary`, data).then(r => r.data),
}

// --- Documents ---
export const documentsApi = {
  list: (collectionId: number) =>
    api.get<Document[]>(`/collections/${collectionId}/documents`).then(r => r.data),
  upload: (collectionId: number, file: File, contextDescription?: string) => {
    const formData = new FormData()
    formData.append('file', file)
    if (contextDescription) formData.append('context_description', contextDescription)
    return api.post<Document>(`/collections/${collectionId}/documents`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(r => r.data)
  },
  delete: (documentId: number) => api.delete(`/documents/${documentId}`),
  updateContext: (documentId: number, data: { context_description?: string; glossary?: Record<string, string> }) =>
    api.put(`/documents/${documentId}/context`, data).then(r => r.data),
  getStatus: (documentId: number) => api.get(`/documents/${documentId}/status`).then(r => r.data),
}

// --- Chat ---
export const chatApi = {
  listConversations: () => api.get<Conversation[]>('/conversations').then(r => r.data),
  createConversation: () => api.post<Conversation>('/conversations').then(r => r.data),
  deleteConversation: (id: number) => api.delete(`/conversations/${id}`),
  ask: (question: string, conversationId?: number, collectionIds?: number[]) =>
    api.post<ChatResponse>('/chat', { question, conversation_id: conversationId, collection_ids: collectionIds }).then(r => r.data),
  updateSelectedCollections: (collectionIds: number[]) =>
    api.put('/chat/collections', { collection_ids: collectionIds }),
}

export default api
