/**
 * Chat Store - State Management für Chat und Collection-Auswahl.
 */

import { create } from 'zustand'
import type { Conversation, Message, Collection, ChatResponse, SourceChunk, RagChunk, ChatMode } from '../types'
import { chatApi, collectionsApi, settingsApi } from '../services/api'

interface ChatState {
  conversations: Conversation[]
  currentConversationId: number | null
  messages: Message[]
  collections: Collection[]
  selectedCollectionIds: number[]
  isLoading: boolean
  streamingContent: string
  globalContext: string
  chatMode: ChatMode
  enableThinking: boolean

  loadConversations: () => Promise<void>
  selectConversation: (id: number) => Promise<void>
  createConversation: () => Promise<void>
  deleteConversation: (id: number) => Promise<void>
  sendMessage: (question: string) => Promise<ChatResponse>
  sendMessageStream: (question: string) => Promise<void>
  loadCollections: () => Promise<void>
  toggleCollection: (id: number) => void
  setSelectedCollections: (ids: number[]) => void
  clearChat: () => void
  loadGlobalContext: () => Promise<void>
  updateGlobalContext: (text: string) => Promise<void>
  updateCollectionContext: (collectionId: number, text: string) => Promise<void>
  setChatMode: (mode: ChatMode) => void
  setEnableThinking: (enabled: boolean) => void
}

export const useChatStore = create<ChatState>((set, get) => ({
  conversations: [],
  currentConversationId: null,
  messages: [],
  collections: [],
  selectedCollectionIds: [],
  isLoading: false,
  streamingContent: '',
  globalContext: '',
  chatMode: 'rag',
  enableThinking: false,

  loadConversations: async () => {
    const conversations = await chatApi.listConversations()
    set({ conversations })
  },

  selectConversation: async (id) => {
    set({ currentConversationId: id, messages: [], isLoading: true })
    try {
      const messages = await chatApi.getMessages(id)
      set({ messages, isLoading: false })
    } catch {
      set({ isLoading: false })
    }
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
    const { currentConversationId, selectedCollectionIds, chatMode, enableThinking } = get()
    set({ isLoading: true })
    try {
      const response = await chatApi.ask(
        question,
        currentConversationId ?? undefined,
        selectedCollectionIds,
        chatMode,
        enableThinking,
      )

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

      get().loadConversations()
      return response
    } finally {
      set({ isLoading: false })
    }
  },

  sendMessageStream: async (question) => {
    const { currentConversationId, selectedCollectionIds, chatMode, enableThinking } = get()

    const userMsg: Message = {
      id: Date.now(),
      role: 'user',
      content: question,
      sources: [],
      created_at: new Date().toISOString(),
    }

    set((state) => ({
      messages: [...state.messages, userMsg],
      isLoading: true,
      streamingContent: '',
    }))

    try {
      const response = await chatApi.askStream(
        question,
        currentConversationId ?? undefined,
        selectedCollectionIds,
        chatMode,
        enableThinking,
      )

      if (!response.ok) {
        const errorText = await response.text()
        throw new Error(errorText || 'Streaming-Fehler')
      }

      const reader = response.body?.getReader()
      if (!reader) throw new Error('Kein Stream verfügbar')

      const decoder = new TextDecoder()
      let fullContent = ''
      let sources: SourceChunk[] = []
      let conversationId = currentConversationId
      let enrichedQuery: string | null = null
      let ragChunks: RagChunk[] = []
      let thoughtProcess: string | null = null

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const text = decoder.decode(value, { stream: true })
        const lines = text.split('\n')

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const jsonStr = line.slice(6).trim()
          if (!jsonStr) continue

          try {
            const event = JSON.parse(jsonStr)

            if (event.type === 'token') {
              fullContent += event.content
              set({ streamingContent: fullContent })
            } else if (event.type === 'debug_info') {
              enrichedQuery = event.enriched_query
              ragChunks = event.rag_chunks || []
              // Attach enriched_query to the user message
              set((state) => ({
                messages: state.messages.map((m) =>
                  m.id === userMsg.id ? { ...m, enriched_query: enrichedQuery } : m
                ),
              }))
            } else if (event.type === 'sources') {
              sources = event.sources
            } else if (event.type === 'done') {
              conversationId = event.conversation_id
              thoughtProcess = event.thought_process || null
            } else if (event.type === 'error') {
              throw new Error(event.content)
            }
          } catch (e) {
            if (e instanceof SyntaxError) continue
            throw e
          }
        }
      }

      const assistantMsg: Message = {
        id: Date.now() + 1,
        role: 'assistant',
        content: fullContent,
        sources,
        enriched_query: enrichedQuery,
        rag_chunks: ragChunks,
        thought_process: thoughtProcess,
        created_at: new Date().toISOString(),
      }

      set((state) => ({
        messages: [...state.messages, assistantMsg],
        currentConversationId: conversationId,
        streamingContent: '',
      }))

      get().loadConversations()
    } catch (error) {
      const errorMsg: Message = {
        id: Date.now() + 1,
        role: 'assistant',
        content: `Fehler: ${error instanceof Error ? error.message : 'Unbekannter Fehler'}`,
        sources: [],
        created_at: new Date().toISOString(),
      }
      set((state) => ({
        messages: [...state.messages, errorMsg],
        streamingContent: '',
      }))
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

  clearChat: () => {
    set({ currentConversationId: null, messages: [], streamingContent: '' })
  },

  loadGlobalContext: async () => {
    try {
      const data = await settingsApi.getGlobalContext()
      set({ globalContext: data.context_text })
    } catch {
      // Ignore errors on load
    }
  },

  updateGlobalContext: async (text: string) => {
    set({ globalContext: text })
    await settingsApi.updateGlobalContext(text)
  },

  updateCollectionContext: async (collectionId: number, text: string) => {
    await collectionsApi.update(collectionId, { context_text: text })
    set((state) => ({
      collections: state.collections.map((c) =>
        c.id === collectionId ? { ...c, context_text: text } : c
      ),
    }))
  },

  setChatMode: (mode) => {
    set({ chatMode: mode })
  },

  setEnableThinking: (enabled) => {
    set({ enableThinking: enabled })
  },
}))
