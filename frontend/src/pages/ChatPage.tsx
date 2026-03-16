/**
 * ChatPage - Hauptseite mit Chatfenster, Collection-Auswahl und Konversationsverlauf.
 *
 * Layout:
 * ┌──────────────────────────────────────────────────────┐
 * │ Konversationen │ Collections   │  Chat-Fenster       │
 * │                │               │                     │
 * │ > Konv 1       │ [x] Normen    │  Frage...           │
 * │   Konv 2       │ [x] Daten     │  Antwort (Markdown) │
 * │   Konv 3       │ [ ] Anfragen  │  [Debug aufklappbar]│
 * │                │               │                     │
 * │ [+ Neuer Chat] │               │ ┌─────────────────┐ │
 * │                │               │ │ Eingabefeld     │ │
 * │                │               │ └─────────────────┘ │
 * └──────────────────────────────────────────────────────┘
 */

import { useEffect, useRef, useState, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import { useChatStore } from '../stores/chatStore'
import { settingsApi } from '../services/api'
import type { SourceChunk, RagChunk } from '../types'
import type { OllamaModel, ModelConfig } from '../services/api'

// =============================================================================
// SourcesPanel - Quellen anzeigen
// =============================================================================

function SourcesPanel({ sources }: { sources: SourceChunk[] }) {
  const [expanded, setExpanded] = useState(false)

  if (sources.length === 0) return null

  return (
    <div className="mt-3 pt-3 border-t border-gray-200">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 text-xs font-semibold text-gray-500 hover:text-gray-700 transition"
      >
        <span className={`inline-block transition-transform ${expanded ? 'rotate-90' : ''}`}>&#9654;</span>
        {sources.length} Quelle{sources.length !== 1 ? 'n' : ''}
      </button>
      {expanded && (
        <div className="mt-2 space-y-2">
          {sources.map((src, i) => (
            <div key={i} className="bg-gray-50 rounded p-2 text-xs">
              <div className="flex items-center gap-2 font-medium text-gray-700">
                <span className="bg-atlas-100 text-atlas-700 px-1.5 py-0.5 rounded text-[10px] font-bold">
                  {i + 1}
                </span>
                {src.document_name}
                {src.page_number && <span className="text-gray-400">S. {src.page_number}</span>}
                <span className="text-gray-400 ml-auto">{src.collection_name}</span>
              </div>
              {src.content_preview && (
                <p className="mt-1 text-gray-500 line-clamp-3">{src.content_preview}</p>
              )}
              {src.similarity_score > 0 && (
                <div className="mt-1 flex items-center gap-1">
                  <div className="h-1 w-16 bg-gray-200 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-atlas-500 rounded-full"
                      style={{ width: `${Math.round(src.similarity_score * 100)}%` }}
                    />
                  </div>
                  <span className="text-[10px] text-gray-400">{Math.round(src.similarity_score * 100)}%</span>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// =============================================================================
// DebugPanel - Query + RAG-Chunks unterhalb einer Nachricht
// =============================================================================

function DebugPanel({
  enrichedQuery,
  originalQuery,
  ragChunks,
}: {
  enrichedQuery?: string | null
  originalQuery?: string
  ragChunks?: RagChunk[]
}) {
  const [open, setOpen] = useState(false)
  const [activeTab, setActiveTab] = useState<'query' | 'chunks'>('query')

  const hasQuery = !!enrichedQuery || !!originalQuery
  const hasChunks = ragChunks && ragChunks.length > 0
  if (!hasQuery && !hasChunks) return null

  return (
    <div className="mt-1">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 text-[10px] text-gray-400 hover:text-gray-600 transition"
        title="RAG-Debug anzeigen"
      >
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
        </svg>
        <span>{open ? 'Debug ausblenden' : 'Debug'}</span>
      </button>
      {open && (
        <div className="mt-1.5 bg-gray-50 border border-gray-200 rounded-lg text-xs overflow-hidden">
          {/* Tabs */}
          <div className="flex border-b border-gray-200 bg-gray-100">
            {hasQuery && (
              <button
                onClick={() => setActiveTab('query')}
                className={`px-3 py-1.5 text-xs font-medium transition ${
                  activeTab === 'query'
                    ? 'text-atlas-700 border-b-2 border-atlas-500 bg-white'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                Query
              </button>
            )}
            {hasChunks && (
              <button
                onClick={() => setActiveTab('chunks')}
                className={`px-3 py-1.5 text-xs font-medium transition ${
                  activeTab === 'chunks'
                    ? 'text-atlas-700 border-b-2 border-atlas-500 bg-white'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                Chunks ({ragChunks!.length})
              </button>
            )}
          </div>

          {/* Tab Content */}
          <div className="p-3 max-h-80 overflow-y-auto">
            {activeTab === 'query' && hasQuery && (
              <div className="space-y-2">
                {originalQuery && (
                  <div>
                    <span className="font-semibold text-gray-500 block mb-0.5">Original-Query:</span>
                    <p className="bg-white border rounded p-2 whitespace-pre-wrap text-gray-700">{originalQuery}</p>
                  </div>
                )}
                {enrichedQuery && (
                  <div>
                    <span className="font-semibold text-gray-500 block mb-0.5">
                      Angereicherte Query{enrichedQuery === originalQuery ? ' (identisch)' : ''}:
                    </span>
                    <p className={`bg-white border rounded p-2 whitespace-pre-wrap ${
                      enrichedQuery !== originalQuery ? 'text-atlas-700 border-atlas-200 bg-atlas-50' : 'text-gray-700'
                    }`}>{enrichedQuery}</p>
                  </div>
                )}
              </div>
            )}
            {activeTab === 'chunks' && hasChunks && (
              <div className="space-y-3">
                {ragChunks!.map((chunk, i) => (
                  <div key={i} className="bg-white border rounded p-2">
                    <div className="flex items-center gap-2 mb-1 text-[10px]">
                      <span className="bg-atlas-100 text-atlas-700 px-1.5 py-0.5 rounded font-bold">{i + 1}</span>
                      <span className="font-medium text-gray-700">{chunk.document_name}</span>
                      {chunk.page_number && <span className="text-gray-400">S. {chunk.page_number}</span>}
                      <span className="text-gray-400">{chunk.collection_name}</span>
                      <span className="ml-auto text-gray-400">{Math.round(chunk.similarity_score * 100)}%</span>
                    </div>
                    <p className="whitespace-pre-wrap text-gray-600 text-[11px] leading-relaxed">{chunk.content}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// =============================================================================
// ChatPage
// =============================================================================

export default function ChatPage() {
  const {
    conversations, currentConversationId, messages, collections,
    selectedCollectionIds, isLoading, streamingContent, globalContext, chatMode,
    loadConversations, selectConversation,
    deleteConversation, loadCollections, toggleCollection,
    sendMessageStream, clearChat, loadGlobalContext,
    updateGlobalContext, setChatMode,
  } = useChatStore()

  const [input, setInput] = useState('')
  const [showGlobalContext, setShowGlobalContext] = useState(false)
  const [globalContextDraft, setGlobalContextDraft] = useState('')
  const [showModelConfig, setShowModelConfig] = useState(false)
  const [modelConfig, setModelConfig] = useState<ModelConfig | null>(null)
  const [availableModels, setAvailableModels] = useState<OllamaModel[]>([])
  const [modelSaving, setModelSaving] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    loadCollections()
    loadConversations()
    loadGlobalContext()
    settingsApi.getModelConfig().then(setModelConfig).catch(() => {})
  }, [loadCollections, loadConversations, loadGlobalContext])

  const handleToggleModelConfig = useCallback(() => {
    if (!showModelConfig && availableModels.length === 0) {
      settingsApi.getAvailableModels()
        .then((data) => setAvailableModels(data.models))
        .catch(() => {})
    }
    setShowModelConfig(!showModelConfig)
  }, [showModelConfig, availableModels.length])

  const handleModelChange = useCallback(async (field: 'llm_model' | 'embedding_model', value: string) => {
    if (!modelConfig) return
    setModelSaving(true)
    try {
      const updated = await settingsApi.updateModelConfig({ [field]: value })
      setModelConfig(updated)
    } catch {
      // Ignore - user may not have admin rights
    } finally {
      setModelSaving(false)
    }
  }, [modelConfig])

  const handleSaveGlobalContext = useCallback(() => {
    updateGlobalContext(globalContextDraft)
    setShowGlobalContext(false)
  }, [globalContextDraft, updateGlobalContext])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingContent])

  const handleSend = async () => {
    if (!input.trim() || isLoading) return
    const question = input
    setInput('')
    await sendMessageStream(question)
  }

  // Für das Debug-Panel: Original-Query der vorangehenden User-Nachricht finden
  const getOriginalQuery = (msgIndex: number): string | undefined => {
    if (messages[msgIndex]?.role === 'assistant' && msgIndex > 0 && messages[msgIndex - 1]?.role === 'user') {
      return messages[msgIndex - 1].content
    }
    return undefined
  }

  return (
    <div className="flex h-full">
      {/* Konversations-Sidebar */}
      <div className="w-56 border-r bg-gray-50 flex flex-col">
        <div className="p-3 border-b">
          <button
            onClick={() => clearChat()}
            className="w-full px-3 py-2 text-sm bg-atlas-600 text-white rounded-lg hover:bg-atlas-700 transition"
          >
            + Neuer Chat
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {conversations.map((conv) => (
            <div
              key={conv.id}
              className={`group flex items-center px-3 py-2 text-sm cursor-pointer hover:bg-gray-100 border-b border-gray-100 ${
                conv.id === currentConversationId ? 'bg-white shadow-sm border-l-2 border-l-atlas-500' : ''
              }`}
            >
              <div
                className="flex-1 min-w-0"
                onClick={() => selectConversation(conv.id)}
              >
                <p className="truncate font-medium text-gray-700">
                  {conv.title || 'Neue Konversation'}
                </p>
                <p className="text-xs text-gray-400">
                  {conv.message_count} Nachricht{conv.message_count !== 1 ? 'en' : ''}
                </p>
              </div>
              <button
                onClick={(e) => { e.stopPropagation(); deleteConversation(conv.id) }}
                className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 ml-1 transition"
                title="Löschen"
              >
                &#10005;
              </button>
            </div>
          ))}
          {conversations.length === 0 && (
            <p className="text-xs text-gray-400 text-center mt-4 px-3">
              Noch keine Konversationen
            </p>
          )}
        </div>
      </div>

      {/* Collection-Sidebar */}
      <div className="w-64 border-r bg-white p-4 overflow-y-auto flex flex-col">
        {/* Globaler Kontext */}
        <div className="mb-3 pb-3 border-b border-gray-200">
          <button
            onClick={() => { setShowGlobalContext(!showGlobalContext); setGlobalContextDraft(globalContext) }}
            className="flex items-center gap-1 text-xs font-semibold text-gray-500 hover:text-atlas-600 uppercase w-full"
          >
            <span className={`inline-block transition-transform text-[10px] ${showGlobalContext ? 'rotate-90' : ''}`}>&#9654;</span>
            Allgemeiner Kontext
            {globalContext && <span className="ml-auto w-2 h-2 rounded-full bg-atlas-500 shrink-0" title="Kontext gesetzt" />}
          </button>
          {showGlobalContext && (
            <div className="mt-2">
              <textarea
                value={globalContextDraft}
                onChange={(e) => setGlobalContextDraft(e.target.value)}
                placeholder="Allgemeiner Kontext für alle Collections, z.B. Erklärungen zu Variablen und Abkürzungen..."
                className="w-full text-xs p-2 border rounded resize-none focus:ring-1 focus:ring-atlas-500 outline-none"
                rows={4}
              />
              <button
                onClick={handleSaveGlobalContext}
                className="mt-1 text-[10px] px-2 py-0.5 bg-atlas-600 text-white rounded hover:bg-atlas-700"
              >
                Speichern
              </button>
            </div>
          )}
        </div>

        {/* Modell-Konfiguration */}
        <div className="mb-3 pb-3 border-b border-gray-200">
          <button
            onClick={handleToggleModelConfig}
            className="flex items-center gap-1 text-xs font-semibold text-gray-500 hover:text-atlas-600 uppercase w-full"
          >
            <span className={`inline-block transition-transform text-[10px] ${showModelConfig ? 'rotate-90' : ''}`}>&#9654;</span>
            Modelle
            {modelConfig && (
              <span className="ml-auto text-[10px] normal-case font-normal text-gray-400 truncate max-w-[120px]">
                {modelConfig.llm_model}
              </span>
            )}
          </button>
          {showModelConfig && modelConfig && (
            <div className="mt-2 space-y-2">
              <div>
                <label className="text-[10px] font-medium text-gray-500 block mb-0.5">Sprachmodell (LLM)</label>
                <select
                  value={modelConfig.llm_model}
                  onChange={(e) => handleModelChange('llm_model', e.target.value)}
                  disabled={modelSaving}
                  className="w-full text-xs p-1.5 border rounded focus:ring-1 focus:ring-atlas-500 outline-none bg-white"
                >
                  {!availableModels.some(m => m.name === modelConfig.llm_model) && (
                    <option value={modelConfig.llm_model}>{modelConfig.llm_model}</option>
                  )}
                  {availableModels.map((m) => (
                    <option key={m.name} value={m.name}>
                      {m.name} {m.parameter_size ? `(${m.parameter_size})` : ''}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-[10px] font-medium text-gray-500 block mb-0.5">Embedding-Modell</label>
                <select
                  value={modelConfig.embedding_model}
                  onChange={(e) => handleModelChange('embedding_model', e.target.value)}
                  disabled={modelSaving}
                  className="w-full text-xs p-1.5 border rounded focus:ring-1 focus:ring-atlas-500 outline-none bg-white"
                >
                  {!availableModels.some(m => m.name === modelConfig.embedding_model) && (
                    <option value={modelConfig.embedding_model}>{modelConfig.embedding_model}</option>
                  )}
                  {availableModels.map((m) => (
                    <option key={m.name} value={m.name}>
                      {m.name} {m.parameter_size ? `(${m.parameter_size})` : ''}
                    </option>
                  ))}
                </select>
              </div>
              {modelSaving && (
                <p className="text-[10px] text-atlas-600">Speichern...</p>
              )}
            </div>
          )}
        </div>


        {/* Chat-Modus */}
        <div className="mb-3 pb-3 border-b border-gray-200">
          <p className="text-xs font-semibold text-gray-500 uppercase mb-2">Modus</p>
          <div className="grid grid-cols-2 gap-2">
            <button
              onClick={() => setChatMode('rag')}
              className={`px-2 py-1.5 text-xs rounded border transition ${chatMode === 'rag'
                ? 'bg-atlas-600 text-white border-atlas-600'
                : 'bg-white text-gray-600 border-gray-300 hover:border-atlas-300'}`}
            >
              RAG
            </button>
            <button
              onClick={() => setChatMode('chat')}
              className={`px-2 py-1.5 text-xs rounded border transition ${chatMode === 'chat'
                ? 'bg-atlas-600 text-white border-atlas-600'
                : 'bg-white text-gray-600 border-gray-300 hover:border-atlas-300'}`}
            >
              Nur Chat
            </button>
          </div>
        </div>

        {/* Collections */}
        <h3 className="font-semibold text-sm text-gray-500 uppercase mb-3">Collections</h3>
        {collections.length === 0 && (
          <p className="text-xs text-gray-400">Keine Collections verfügbar</p>
        )}
        {collections.map((col) => (
          <div key={col.id} className="p-2 hover:bg-gray-50 rounded">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={selectedCollectionIds.includes(col.id)}
                onChange={() => toggleCollection(col.id)}
                className="rounded border-gray-300 text-atlas-600 focus:ring-atlas-500"
              />
              <span className="text-sm truncate">{col.name}</span>
              <span className="text-xs text-gray-400 ml-auto shrink-0">{col.document_count}</span>
            </label>
          </div>
        ))}
      </div>

      {/* Chat-Bereich */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Nachrichten */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {messages.length === 0 && !streamingContent && (
            <div className="text-center text-gray-400 mt-20">
              <div className="text-5xl mb-4">&#128218;</div>
              <h2 className="text-xl font-medium">Willkommen bei Atlas</h2>
              <p className="mt-2">{chatMode === 'rag' ? 'Stellen Sie eine Frage zu Ihren Dokumenten.' : 'Stellen Sie eine freie Frage an das Modell.'}</p>
              {chatMode === 'rag' && selectedCollectionIds.length === 0 && (
                <p className="mt-4 text-sm text-amber-500">
                  Bitte wählen Sie mindestens eine Collection aus.
                </p>
              )}
            </div>
          )}
          {messages.map((msg, idx) => (
            <div key={msg.id} className={`flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
              <div className={`max-w-3xl rounded-lg p-4 ${
                msg.role === 'user'
                  ? 'bg-atlas-600 text-white'
                  : 'bg-white border shadow-sm'
              }`}>
                {msg.role === 'user' ? (
                  <p className="whitespace-pre-wrap">{msg.content}</p>
                ) : (
                  <div className="prose prose-sm max-w-none prose-headings:mt-3 prose-headings:mb-1 prose-p:my-1 prose-li:my-0">
                    <ReactMarkdown>{msg.content}</ReactMarkdown>
                  </div>
                )}
                <SourcesPanel sources={msg.sources} />
              </div>
              {/* Debug-Panel unter jeder Assistenten-Nachricht */}
              {chatMode === 'rag' && msg.role === 'assistant' && (
                <div className="max-w-3xl w-full">
                  <DebugPanel
                    enrichedQuery={msg.enriched_query}
                    originalQuery={getOriginalQuery(idx)}
                    ragChunks={msg.rag_chunks}
                  />
                </div>
              )}
            </div>
          ))}
          {/* Streaming-Anzeige */}
          {isLoading && streamingContent && (
            <div className="flex justify-start">
              <div className="max-w-3xl bg-white border rounded-lg p-4 shadow-sm">
                <div className="prose prose-sm max-w-none prose-headings:mt-3 prose-headings:mb-1 prose-p:my-1 prose-li:my-0">
                  <ReactMarkdown>{streamingContent}</ReactMarkdown>
                </div>
                <span className="inline-block w-2 h-4 bg-atlas-500 animate-pulse ml-0.5" />
              </div>
            </div>
          )}
          {/* Loading-Animation (kein Streaming-Content) */}
          {isLoading && !streamingContent && (
            <div className="flex justify-start">
              <div className="bg-white border rounded-lg p-4 shadow-sm">
                <div className="flex items-center gap-2">
                  <div className="flex space-x-1">
                    <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" />
                    <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.1s' }} />
                    <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }} />
                  </div>
                  <span className="text-xs text-gray-400">Suche und generiere Antwort...</span>
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Eingabefeld */}
        <div className="border-t p-4 bg-white">
          <div className="flex gap-3 max-w-4xl mx-auto">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
              placeholder="Stellen Sie eine Frage..."
              className="flex-1 p-3 border rounded-lg focus:ring-2 focus:ring-atlas-500 outline-none"
              disabled={isLoading}
            />
            <button
              onClick={handleSend}
              disabled={isLoading || !input.trim() || (chatMode === 'rag' && selectedCollectionIds.length === 0)}
              className="px-6 py-3 bg-atlas-600 text-white rounded-lg hover:bg-atlas-700 disabled:opacity-50 transition"
            >
              Senden
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
