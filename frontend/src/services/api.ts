/**
 * Atlas API Client
 *
 * Zentraler HTTP-Client für alle Backend-Kommunikation.
 * Fügt automatisch den JWT-Token zu Requests hinzu.
 */

import axios from 'axios'
import type {
  LoginResponse, Collection, Document, AccessInfo,
  Conversation, Message, ChatResponse, Group, UserDetail,
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
  removeAccess: (collectionId: number, groupId: number) =>
    api.delete(`/collections/${collectionId}/access/${groupId}`),
  getAccess: (collectionId: number) =>
    api.get<AccessInfo[]>(`/collections/${collectionId}/access`).then(r => r.data),
}

// --- Documents ---
export const documentsApi = {
  list: (collectionId: number) =>
    api.get<Document[]>(`/collections/${collectionId}/documents`).then(r => r.data),
  upload: (collectionId: number, file: File, onProgress?: (percent: number) => void) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post<Document>(`/collections/${collectionId}/documents`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e) => {
        if (onProgress && e.total) {
          onProgress(Math.round((e.loaded * 100) / e.total))
        }
      },
    }).then(r => r.data)
  },
  delete: (documentId: number) => api.delete(`/documents/${documentId}`),
  getStatus: (documentId: number) => api.get(`/documents/${documentId}/status`).then(r => r.data),
}

// --- Settings ---
export interface ModelConfig {
  llm_model: string
  embedding_model: string
}

export interface OllamaModel {
  name: string
  size: number | null
  parameter_size: string | null
}

export const settingsApi = {
  getGlobalContext: () =>
    api.get<{ context_text: string }>('/settings/global-context').then(r => r.data),
  updateGlobalContext: (contextText: string) =>
    api.put<{ context_text: string }>('/settings/global-context', { context_text: contextText }).then(r => r.data),
  getModelConfig: () =>
    api.get<ModelConfig>('/settings/models').then(r => r.data),
  updateModelConfig: (data: { llm_model?: string; embedding_model?: string }) =>
    api.put<ModelConfig>('/settings/models', data).then(r => r.data),
  getAvailableModels: () =>
    api.get<{ models: OllamaModel[] }>('/settings/models/available').then(r => r.data),
}


export interface DockerContainerInfo {
  id: string
  name: string
  image: string
  status: string
}

export interface DockerImageInfo {
  id: string
  tags: string[]
}

export interface DockerVolumeInfo {
  name: string
}

export interface DockerResourcesResponse {
  containers: DockerContainerInfo[]
  images: DockerImageInfo[]
  volumes: DockerVolumeInfo[]
}

export interface DockerActionRequest {
  container_ids?: string[]
  image_ids?: string[]
  volume_names?: string[]
  stop_containers?: boolean
  restart_containers?: boolean
  remove_containers?: boolean
  remove_images?: boolean
  rebuild_images?: boolean
  remove_volumes?: boolean
}

// --- Chat ---
export const chatApi = {
  listConversations: () => api.get<Conversation[]>('/conversations').then(r => r.data),
  createConversation: () => api.post<Conversation>('/conversations').then(r => r.data),
  deleteConversation: (id: number) => api.delete(`/conversations/${id}`),
  getMessages: (conversationId: number) =>
    api.get<Message[]>(`/conversations/${conversationId}/messages`).then(r => r.data),
  ask: (question: string, conversationId?: number, collectionIds?: number[]) =>
    api.post<ChatResponse>('/chat', { question, conversation_id: conversationId, collection_ids: collectionIds }).then(r => r.data),
  askStream: (question: string, conversationId?: number, collectionIds?: number[]) => {
    const token = localStorage.getItem('atlas_token')
    return fetch('/api/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ question, conversation_id: conversationId, collection_ids: collectionIds }),
    })
  },
  updateSelectedCollections: (collectionIds: number[]) =>
    api.put('/chat/collections', { collection_ids: collectionIds }),
}



export const dockerAdminApi = {
  getResources: () => api.get<DockerResourcesResponse>('/settings/docker/resources').then(r => r.data),
  runActions: (data: DockerActionRequest) =>
    api.post<{ messages: string[] }>('/settings/docker/actions', data).then(r => r.data),
  triggerRepoUpdate: () =>
    api.post<{ started: boolean; message: string }>('/settings/repo/update').then(r => r.data),
}

export default api
