/**
 * ChatPage - Hauptseite mit Chatfenster, Collection-Auswahl und Konversationsverlauf.
 *
 * Layout:
 * ┌──────────────────────────────────────────────────────┐
 * │ Konversationen │ Collections   │  Chat-Fenster       │
 * │                │               │                     │
 * │ > Konv 1       │ [x] Normen    │  Frage...           │
 * │   Konv 2       │ [x] Daten     │  Antwort (Markdown) │
 * │   Konv 3       │ [ ] Anfragen  │  [Quellen klappbar] │
 * │                │               │                     │
 * │ [+ Neuer Chat] │               │ ┌─────────────────┐ │
 * │                │               │ │ Eingabefeld     │ │
 * │                │               │ └─────────────────┘ │
 * └──────────────────────────────────────────────────────┘
 */

import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { useChatStore } from '../stores/chatStore'
import type { SourceChunk } from '../types'

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

export default function ChatPage() {
  const {
    conversations, currentConversationId, messages, collections,
    selectedCollectionIds, isLoading, streamingContent,
    loadConversations, selectConversation,
    deleteConversation, loadCollections, toggleCollection,
    sendMessageStream, clearChat,
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
    const question = input
    setInput('')
    await sendMessageStream(question)
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
      <div className="w-56 border-r bg-white p-4 overflow-y-auto">
        <h3 className="font-semibold text-sm text-gray-500 uppercase mb-3">Collections</h3>
        {collections.length === 0 && (
          <p className="text-xs text-gray-400">Keine Collections verfügbar</p>
        )}
        {collections.map((col) => (
          <label key={col.id} className="flex items-center gap-2 p-2 hover:bg-gray-50 rounded cursor-pointer">
            <input
              type="checkbox"
              checked={selectedCollectionIds.includes(col.id)}
              onChange={() => toggleCollection(col.id)}
              className="rounded border-gray-300 text-atlas-600 focus:ring-atlas-500"
            />
            <span className="text-sm truncate">{col.name}</span>
            <span className="text-xs text-gray-400 ml-auto shrink-0">{col.document_count}</span>
          </label>
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
              <p className="mt-2">Stellen Sie eine Frage zu Ihren Dokumenten.</p>
              {selectedCollectionIds.length === 0 && (
                <p className="mt-4 text-sm text-amber-500">
                  Bitte wählen Sie mindestens eine Collection aus.
                </p>
              )}
            </div>
          )}
          {messages.map((msg) => (
            <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
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
              disabled={isLoading || !input.trim() || selectedCollectionIds.length === 0}
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
