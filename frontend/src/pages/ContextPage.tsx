/**
 * ContextPage - Allgemeiner Kontext für alle Collections und Suchanfragen.
 */

import { useEffect, useState } from 'react'
import { settingsApi } from '../services/api'

export default function ContextPage() {
  const [globalContext, setGlobalContext] = useState('')
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    settingsApi.getGlobalContext().then((d) => {
      setGlobalContext(d.context_text)
      setDraft(d.context_text)
      setLoaded(true)
    }).catch(() => setLoaded(true))
  }, [])

  const handleSave = async () => {
    setSaving(true)
    try {
      await settingsApi.updateGlobalContext(draft)
      setGlobalContext(draft)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col h-full p-6">
      <div className="mb-4">
        <h1 className="text-xl font-bold text-gray-800">Allgemeiner Kontext</h1>
        <p className="text-sm text-gray-500 mt-1">
          Kontext der bei allen Suchanfragen und für alle Collections verwendet wird.
          Variablen, Abkürzungen, Fachbegriffe und Hintergrundinformationen.
        </p>
      </div>

      {loaded ? (
        <>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="z.B. L1 = Kühlerlänge, B2 = Gehäusebreite, VEM = Vereinigte Elektrizitätswerke Mansfeld..."
            className="flex-1 w-full text-sm p-4 border rounded-lg resize-none focus:ring-2 focus:ring-atlas-500 outline-none bg-white"
          />
          <div className="mt-3 flex items-center gap-3">
            <button
              onClick={handleSave}
              disabled={saving || draft === globalContext}
              className="px-6 py-2 text-sm bg-atlas-600 text-white rounded-lg hover:bg-atlas-700 disabled:opacity-50 transition"
            >
              {saving ? 'Speichern...' : 'Kontext speichern'}
            </button>
            {draft !== globalContext && (
              <span className="text-xs text-amber-500">Ungespeicherte Änderungen</span>
            )}
          </div>
        </>
      ) : (
        <div className="flex-1 flex items-center justify-center text-gray-400">
          Laden...
        </div>
      )}
    </div>
  )
}
