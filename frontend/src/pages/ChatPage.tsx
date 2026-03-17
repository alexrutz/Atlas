/**
 * ChatPage - Hauptseite mit Chatfenster, Collection-Auswahl und Konversationsverlauf.
 */

import { useEffect, useRef, useState, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import { useChatStore } from '../stores/chatStore'
import type { SourceChunk, RagChunk } from '../types'

// =============================================================================
// SourcesPanel
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
// DebugPanel - Query + RAG-Chunks + Thinking unterhalb einer Nachricht
// =============================================================================

function DebugPanel({
  enrichedQuery,
  originalQuery,
  ragChunks,
  thinking,
}: {
  enrichedQuery?: string | null
  originalQuery?: string
  ragChunks?: RagChunk[]
  thinking?: string | null
}) {
  const [open, setOpen] = useState(false)
  const [activeTab, setActiveTab] = useState<'query' | 'chunks' | 'thinking'>('query')

  const hasQuery = !!enrichedQuery || !!originalQuery
  const hasChunks = ragChunks && ragChunks.length > 0
  const hasThinking = !!thinking
  if (!hasQuery && !hasChunks && !hasThinking) return null

  // Auto-select first available tab
  const firstTab = hasThinking ? 'thinking' : hasQuery ? 'query' : 'chunks'

  return (
    <div className="mt-1">
      <button
        onClick={() => { setOpen(!open); if (!open) setActiveTab(firstTab) }}
        className="flex items-center gap-1 text-[10px] text-gray-400 hover:text-gray-600 transition"
        title="Debug anzeigen"
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
            {hasThinking && (
              <button
                onClick={() => setActiveTab('thinking')}
                className={`px-3 py-1.5 text-xs font-medium transition ${
                  activeTab === 'thinking'
                    ? 'text-purple-700 border-b-2 border-purple-500 bg-white'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                Thinking
              </button>
            )}
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
            {activeTab === 'thinking' && hasThinking && (
              <div className="bg-purple-50 border border-purple-200 rounded p-3">
                <p className="whitespace-pre-wrap text-gray-700 text-[11px] leading-relaxed">{thinking}</p>
              </div>
            )}
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
    selectedCollectionIds, isLoading, streamingContent, streamingThinking,
    enableThinking, ragMode,
    loadConversations, selectConversation,
    deleteConversation, loadCollections, toggleCollection,
    sendMessageStream, clearChat,
    setEnableThinking, setRagMode,
  } = useChatStore()

  const [input, setInput] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    loadCollections()
    loadConversations()
  }, [loadCollections, loadConversations])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingContent])

  const handleSend = async () => {
    if (!input.trim() || isLoading) return
    if (ragMode && selectedCollectionIds.length === 0) return
    const question = input
    setInput('')
    await sendMessageStream(question)
  }

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
        {/* RAG / Free Chat Toggle */}
        <div className="mb-3 pb-3 border-b border-gray-200">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-gray-500 uppercase">Modus</span>
            <div className="ml-auto flex items-center gap-1.5">
              <span className={`text-[10px] ${ragMode ? 'text-atlas-600 font-medium' : 'text-gray-400'}`}>RAG</span>
              <button
                onClick={() => setRagMode(!ragMode)}
                className={`relative w-8 h-4 rounded-full transition ${ragMode ? 'bg-atlas-500' : 'bg-gray-300'}`}
              >
                <span className={`absolute top-0.5 w-3 h-3 bg-white rounded-full transition-transform ${
                  ragMode ? 'left-0.5' : 'left-4.5 translate-x-0'
                }`} style={{ left: ragMode ? '2px' : '18px' }} />
              </button>
              <span className={`text-[10px] ${!ragMode ? 'text-purple-600 font-medium' : 'text-gray-400'}`}>Frei</span>
            </div>
          </div>
          {!ragMode && (
            <p className="text-[10px] text-gray-400 mt-1">Direkte Konversation ohne Dokumentenkontext</p>
          )}
        </div>

        {/* Collections */}
        <h3 className="font-semibold text-sm text-gray-500 uppercase mb-3">Collections</h3>
        {collections.length === 0 && (
          <p className="text-xs text-gray-400">Keine Collections verfügbar</p>
        )}
        {collections.map((col) => (
          <div key={col.id} className={`p-2 hover:bg-gray-50 rounded ${!ragMode ? 'opacity-50' : ''}`}>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={selectedCollectionIds.includes(col.id)}
                onChange={() => toggleCollection(col.id)}
                disabled={!ragMode}
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
              <p className="mt-2">
                {ragMode
                  ? 'Stellen Sie eine Frage zu Ihren Dokumenten.'
                  : 'Freier Chat-Modus - sprechen Sie direkt mit dem Modell.'}
              </p>
              {ragMode && selectedCollectionIds.length === 0 && (
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
              {msg.role === 'assistant' && (
                <div className="max-w-3xl w-full">
                  <DebugPanel
                    enrichedQuery={msg.enriched_query}
                    originalQuery={getOriginalQuery(idx)}
                    ragChunks={msg.rag_chunks}
                    thinking={msg.thinking}
                  />
                </div>
              )}
            </div>
          ))}
          {/* Streaming-Anzeige */}
          {isLoading && (streamingContent || streamingThinking) && (
            <div className="flex flex-col items-start gap-1">
              {streamingThinking && (
                <div className="max-w-3xl bg-purple-50 border border-purple-200 rounded-lg p-3 text-xs">
                  <span className="text-purple-600 font-medium text-[10px] block mb-1">Thinking...</span>
                  <p className="whitespace-pre-wrap text-gray-600">{streamingThinking}</p>
                </div>
              )}
              {streamingContent && (
                <div className="max-w-3xl bg-white border rounded-lg p-4 shadow-sm">
                  <div className="prose prose-sm max-w-none prose-headings:mt-3 prose-headings:mb-1 prose-p:my-1 prose-li:my-0">
                    <ReactMarkdown>{streamingContent}</ReactMarkdown>
                  </div>
                  <span className="inline-block w-2 h-4 bg-atlas-500 animate-pulse ml-0.5" />
                </div>
              )}
            </div>
          )}
          {isLoading && !streamingContent && !streamingThinking && (
            <div className="flex justify-start">
              <div className="bg-white border rounded-lg p-4 shadow-sm">
                <div className="flex items-center gap-2">
                  <div className="flex space-x-1">
                    <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" />
                    <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.1s' }} />
                    <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }} />
                  </div>
                  <span className="text-xs text-gray-400">
                    {ragMode ? 'Suche und generiere Antwort...' : 'Generiere Antwort...'}
                  </span>
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
              placeholder={ragMode ? 'Stellen Sie eine Frage...' : 'Nachricht eingeben...'}
              className="flex-1 p-3 border rounded-lg focus:ring-2 focus:ring-atlas-500 outline-none"
              disabled={isLoading}
            />
            <div className="flex flex-col items-center gap-1">
              <button
                onClick={handleSend}
                disabled={isLoading || !input.trim() || (ragMode && selectedCollectionIds.length === 0)}
                className="px-6 py-3 bg-atlas-600 text-white rounded-lg hover:bg-atlas-700 disabled:opacity-50 transition"
              >
                Senden
              </button>
              {/* Thinking Toggle */}
              <label className="flex items-center gap-1 cursor-pointer">
                <input
                  type="checkbox"
                  checked={enableThinking}
                  onChange={(e) => setEnableThinking(e.target.checked)}
                  className="rounded border-gray-300 text-purple-600 focus:ring-purple-500 w-3 h-3"
                />
                <span className="text-[10px] text-gray-500">Thinking</span>
              </label>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
