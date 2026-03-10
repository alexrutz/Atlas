/**
 * ChatPage - Hauptseite mit Chatfenster und Collection-Auswahl.
 *
 * Layout:
 * ┌─────────────────────────────────────────┐
 * │ Sidebar (Collections) │  Chat-Fenster   │
 * │                       │                  │
 * │ [x] Normen            │  Frage...        │
 * │ [x] Datenblätter      │  Antwort...      │
 * │ [ ] Anfragen          │  [Quellen]       │
 * │                       │                  │
 * │                       │ ┌──────────────┐ │
 * │                       │ │ Eingabefeld  │ │
 * │                       │ └──────────────┘ │
 * └─────────────────────────────────────────┘
 */

import { useEffect, useState } from 'react'
import { useChatStore } from '../stores/chatStore'

export default function ChatPage() {
  const {
    messages, collections, selectedCollectionIds, isLoading,
    loadCollections, toggleCollection, sendMessage,
  } = useChatStore()
  const [input, setInput] = useState('')

  useEffect(() => { loadCollections() }, [loadCollections])

  const handleSend = async () => {
    if (!input.trim() || isLoading) return
    const question = input
    setInput('')
    await sendMessage(question)
  }

  return (
    <div className="flex h-full">
      {/* Collection-Sidebar */}
      <div className="w-64 border-r bg-white p-4 overflow-y-auto">
        <h3 className="font-semibold text-sm text-gray-500 uppercase mb-3">Collections</h3>
        {collections.map((col) => (
          <label key={col.id} className="flex items-center gap-2 p-2 hover:bg-gray-50 rounded cursor-pointer">
            <input
              type="checkbox"
              checked={selectedCollectionIds.includes(col.id)}
              onChange={() => toggleCollection(col.id)}
              className="rounded border-gray-300 text-atlas-600 focus:ring-atlas-500"
            />
            <span className="text-sm">{col.name}</span>
            <span className="text-xs text-gray-400 ml-auto">{col.document_count}</span>
          </label>
        ))}
      </div>

      {/* Chat-Bereich */}
      <div className="flex-1 flex flex-col">
        {/* Nachrichten */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {messages.length === 0 && (
            <div className="text-center text-gray-400 mt-20">
              <h2 className="text-xl font-medium">Willkommen bei Atlas</h2>
              <p className="mt-2">Stellen Sie eine Frage zu Ihren Dokumenten.</p>
            </div>
          )}
          {messages.map((msg) => (
            <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-2xl rounded-lg p-4 ${
                msg.role === 'user' ? 'bg-atlas-600 text-white' : 'bg-white border shadow-sm'
              }`}>
                <p className="whitespace-pre-wrap">{msg.content}</p>
                {msg.sources.length > 0 && (
                  <div className="mt-3 pt-3 border-t border-gray-200 space-y-1">
                    <p className="text-xs font-semibold text-gray-500">Quellen:</p>
                    {msg.sources.map((src, i) => (
                      <p key={i} className="text-xs text-gray-500">
                        [{i + 1}] {src.document_name}
                        {src.page_number && ` (S. ${src.page_number})`}
                        {' '}&mdash; {src.collection_name}
                      </p>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
          {isLoading && (
            <div className="flex justify-start">
              <div className="bg-white border rounded-lg p-4 shadow-sm">
                <div className="flex space-x-1">
                  <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" />
                  <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.1s' }} />
                  <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }} />
                </div>
              </div>
            </div>
          )}
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
              disabled={isLoading || !input.trim()}
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
