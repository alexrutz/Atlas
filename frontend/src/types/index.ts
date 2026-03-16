// =============================================================================
// Atlas Frontend - TypeScript Typen
// =============================================================================

// --- Auth ---
export interface User {
  id: number
  username: string
  full_name: string
  is_admin: boolean
}

export interface UserDetail {
  id: number
  username: string
  email: string
  full_name: string
  is_active: boolean
  is_admin: boolean
  created_at: string
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
  user: User
}

// --- Gruppen ---
export interface Group {
  id: number
  name: string
  description: string | null
  created_at: string
  members?: UserBrief[]
}

export interface UserBrief {
  id: number
  username: string
  full_name: string
}

// --- Collections ---
export interface Collection {
  id: number
  name: string
  description: string | null
  context_text: string | null
  created_at: string
  can_read: boolean
  can_write: boolean
  document_count: number
}

// --- Zugriffsrechte ---
export interface AccessInfo {
  group_id: number
  group_name: string
  can_read: boolean
  can_write: boolean
}

// --- Dokumente ---
export interface Document {
  id: number
  collection_id: number
  original_name: string
  file_type: string
  file_size_bytes: number
  processing_status: 'pending' | 'processing' | 'completed' | 'error'
  processing_error: string | null
  chunk_count: number
  created_at: string
}

// --- Chat ---
export type ChatMode = 'rag' | 'chat'

export interface Conversation {
  id: number
  title: string | null
  created_at: string
  message_count: number
}

export interface RagChunk {
  document_name: string
  collection_name: string
  page_number: number | null
  content: string
  similarity_score: number
}

export interface Message {
  id: number
  role: 'user' | 'assistant'
  content: string
  sources: SourceChunk[]
  enriched_query?: string | null
  rag_chunks?: RagChunk[]
  created_at: string
}

export interface SourceChunk {
  chunk_id: number
  document_name: string
  collection_name: string
  content_preview: string
  page_number: number | null
  similarity_score: number
}

export interface ChatResponse {
  answer: string
  conversation_id: number
  sources: SourceChunk[]
}
