/**
 * Chat Store - State Management für Chat und Collection-Auswahl.
 */

import { create } from 'zustand'
import type { Conversation, Message, Collection, ChatResponse } from '../types'
import { chatApi, collectionsApi } from '../services/api'

interface ChatState {
  conversations: Conversation[]
  currentConversationId: number | null
  messages: Message[]
  collections: Collection[]
  selectedCollectionIds: number[]
  isLoading: boolean

  loadConversations: () => Promise<void>
  selectConversation: (id: number) => void
  createConversation: () => Promise<void>
  deleteConversation: (id: number) => Promise<void>
  sendMessage: (question: string) => Promise<ChatResponse>
  loadCollections: () => Promise<void>
  toggleCollection: (id: number) => void
  setSelectedCollections: (ids: number[]) => void
}

export const useChatStore = create<ChatState>((set, get) => ({
  conversations: [],
  currentConversationId: null,
  messages: [],
  collections: [],
  selectedCollectionIds: [],
  isLoading: false,

  loadConversations: async () => {
    const conversations = await chatApi.listConversations()
    set({ conversations })
  },

  selectConversation: (id) => {
    set({ currentConversationId: id, messages: [] })
    // TODO: Nachrichten der Konversation laden
  },

  createConversation: async () => {
    const conv = await chatApi.createConversation()
    set((state) => ({
      conversations: [conv, ...state.conversations],
      currentConversationId: conv.id,
      messages: [],
    }))
  },

  deleteConversation: async (id) => {
    await chatApi.deleteConversation(id)
    set((state) => ({
      conversations: state.conversations.filter(c => c.id !== id),
      currentConversationId: state.currentConversationId === id ? null : state.currentConversationId,
      messages: state.currentConversationId === id ? [] : state.messages,
    }))
  },

  sendMessage: async (question) => {
    const { currentConversationId, selectedCollectionIds } = get()
    set({ isLoading: true })
    try {
      const response = await chatApi.ask(question, currentConversationId ?? undefined, selectedCollectionIds)

      // Nachrichten aktualisieren
      const userMsg: Message = {
        id: Date.now(),
        role: 'user',
        content: question,
        sources: [],
        created_at: new Date().toISOString(),
      }
      const assistantMsg: Message = {
        id: Date.now() + 1,
        role: 'assistant',
        content: response.answer,
        sources: response.sources,
        created_at: new Date().toISOString(),
      }

      set((state) => ({
        messages: [...state.messages, userMsg, assistantMsg],
        currentConversationId: response.conversation_id,
      }))

      return response
    } finally {
      set({ isLoading: false })
    }
  },

  loadCollections: async () => {
    const collections = await collectionsApi.list()
    set({ collections, selectedCollectionIds: collections.map(c => c.id) })
  },

  toggleCollection: (id) => {
    set((state) => {
      const ids = state.selectedCollectionIds.includes(id)
        ? state.selectedCollectionIds.filter(cid => cid !== id)
        : [...state.selectedCollectionIds, id]
      chatApi.updateSelectedCollections(ids)
      return { selectedCollectionIds: ids }
    })
  },

  setSelectedCollections: (ids) => {
    set({ selectedCollectionIds: ids })
    chatApi.updateSelectedCollections(ids)
  },
}))
