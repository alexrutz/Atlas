/**
 * DocumentsPage - Dokumentenverwaltung mit Upload, Kontext-Editor und Glossar.
 *
 * Hier können Benutzer:
 * - Dokumente zu Collections hochladen
 * - Kontext-Beschreibungen hinzufügen (WICHTIG für Context-Enriched Embedding)
 * - Glossar-Einträge verwalten
 * - Den Verarbeitungsstatus einsehen
 */

import { useEffect, useState, useCallback, useRef } from 'react'
import { useDropzone } from 'react-dropzone'
import { collectionsApi, documentsApi } from '../services/api'
import type { Collection, Document as DocType, GlossaryEntry } from '../types'

export default function DocumentsPage() {
  const [collections, setCollections] = useState<Collection[]>([])
  const [selectedCollection, setSelectedCollection] = useState<Collection | null>(null)
  const [documents, setDocuments] = useState<DocType[]>([])
  const [glossary, setGlossary] = useState<GlossaryEntry[]>([])

  const loadCollections = useCallback(async () => {
    const data = await collectionsApi.list()
    setCollections(data)
  }, [])

  useEffect(() => {
    loadCollections()
  }, [loadCollections])

  const loadDocumentsAndGlossary = useCallback(async () => {
    if (!selectedCollection) return
    const [docs, gl] = await Promise.all([
      documentsApi.list(selectedCollection.id),
      collectionsApi.getGlossary(selectedCollection.id),
    ])
    setDocuments(docs)
    setGlossary(gl)
  }, [selectedCollection])

  useEffect(() => {
    loadDocumentsAndGlossary()
  }, [loadDocumentsAndGlossary])

  return (
    <div className="flex h-full">
      {/* Collection-Liste */}
      <div className="w-64 border-r bg-white p-4 overflow-y-auto">
        <h3 className="font-semibold text-sm text-gray-500 uppercase mb-3">Collections</h3>
        {collections.length === 0 && (
          <p className="text-xs text-gray-400">Keine Collections vorhanden. Erstellen Sie eine im Admin-Panel.</p>
        )}
        {collections.map((col) => (
          <button
            key={col.id}
            onClick={() => setSelectedCollection(col)}
            className={`w-full text-left p-2 rounded mb-1 transition ${
              selectedCollection?.id === col.id ? 'bg-atlas-100 text-atlas-700' : 'hover:bg-gray-50'
            }`}
          >
            <div className="font-medium text-sm">{col.name}</div>
            <div className="text-xs text-gray-400">{col.document_count} Dokumente</div>
          </button>
        ))}
      </div>

      {/* Hauptbereich */}
      <div className="flex-1 p-6 overflow-y-auto">
        {!selectedCollection ? (
          <div className="text-center text-gray-400 mt-20">
            Wählen Sie eine Collection aus der Liste.
          </div>
        ) : (
          <div className="max-w-4xl">
            <h2 className="text-xl font-bold mb-4">{selectedCollection.name}</h2>
            {selectedCollection.description && (
              <p className="text-gray-600 mb-6">{selectedCollection.description}</p>
            )}

            {/* Upload-Bereich */}
            <UploadSection
              collectionId={selectedCollection.id}
              onUploadComplete={() => { loadDocumentsAndGlossary(); loadCollections() }}
            />

            {/* Dokumentenliste */}
            <DocumentList
              documents={documents}
              onRefresh={loadDocumentsAndGlossary}
            />

            {/* Glossar */}
            <GlossarySection
              collectionId={selectedCollection.id}
              glossary={glossary}
              onRefresh={loadDocumentsAndGlossary}
            />
          </div>
        )}
      </div>
    </div>
  )
}

// =============================================================================
// Upload Section with react-dropzone
// =============================================================================

function UploadSection({ collectionId, onUploadComplete }: {
  collectionId: number
  onUploadComplete: () => void
}) {
  const [contextDescription, setContextDescription] = useState('')
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [uploadError, setUploadError] = useState('')
  const [uploadSuccess, setUploadSuccess] = useState('')

  const onDrop = useCallback(async (acceptedFiles: File[]) => {
    if (acceptedFiles.length === 0) return

    setUploadError('')
    setUploadSuccess('')

    for (const file of acceptedFiles) {
      setUploading(true)
      setUploadProgress(0)
      try {
        await documentsApi.upload(
          collectionId,
          file,
          contextDescription || undefined,
          (percent) => setUploadProgress(percent),
        )
        setUploadSuccess(`"${file.name}" erfolgreich hochgeladen. Verarbeitung läuft...`)
        setContextDescription('')
        onUploadComplete()
      } catch (err: unknown) {
        const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        setUploadError(msg || `Fehler beim Hochladen von "${file.name}"`)
      } finally {
        setUploading(false)
        setUploadProgress(0)
      }
    }
  }, [collectionId, contextDescription, onUploadComplete])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    disabled: uploading,
    accept: {
      'application/pdf': ['.pdf'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
      'application/msword': ['.doc'],
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
      'application/vnd.ms-excel': ['.xls'],
      'application/vnd.openxmlformats-officedocument.presentationml.presentation': ['.pptx'],
      'text/plain': ['.txt', '.md', '.csv'],
      'text/html': ['.html'],
      'application/json': ['.json'],
      'application/xml': ['.xml'],
    },
    maxSize: 100 * 1024 * 1024,
  })

  return (
    <section className="mb-8">
      <h3 className="font-semibold mb-3">Dokument hochladen</h3>

      {uploadError && (
        <div className="bg-red-50 text-red-600 p-3 rounded text-sm mb-3">{uploadError}</div>
      )}
      {uploadSuccess && (
        <div className="bg-green-50 text-green-600 p-3 rounded text-sm mb-3">{uploadSuccess}</div>
      )}

      <div
        {...getRootProps()}
        className={`border-2 border-dashed rounded-lg p-6 text-center transition cursor-pointer ${
          isDragActive
            ? 'border-atlas-500 bg-atlas-50'
            : uploading
            ? 'border-gray-200 bg-gray-50 cursor-not-allowed'
            : 'border-gray-300 hover:border-atlas-400'
        }`}
      >
        <input {...getInputProps()} />
        {uploading ? (
          <div>
            <p className="text-gray-600 text-sm mb-2">Hochladen... {uploadProgress}%</p>
            <div className="w-full bg-gray-200 rounded-full h-2">
              <div
                className="bg-atlas-600 h-2 rounded-full transition-all"
                style={{ width: `${uploadProgress}%` }}
              />
            </div>
          </div>
        ) : isDragActive ? (
          <p className="text-atlas-600 font-medium">Datei hier ablegen...</p>
        ) : (
          <>
            <p className="text-gray-500">
              Datei hierher ziehen oder klicken zum Auswählen
            </p>
            <p className="text-xs text-gray-400 mt-1">
              PDF, DOCX, XLSX, PPTX, TXT, CSV, HTML (max. 100 MB)
            </p>
          </>
        )}
      </div>

      <div className="mt-3 p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
        <p className="text-sm font-medium text-yellow-800">
          Kontext-Beschreibung (empfohlen)
        </p>
        <p className="text-xs text-yellow-700 mt-1">
          Beschreiben Sie den Inhalt des Dokuments und erklären Sie Fachbegriffe
          und Abkürzungen. Dies verbessert die Suchqualität erheblich.
        </p>
        <textarea
          value={contextDescription}
          onChange={(e) => setContextDescription(e.target.value)}
          placeholder="z.B.: Dieses Dokument ist die DIN EN 1090-2 Norm. EXC = Ausführungsklasse, WPS = Schweißanweisung..."
          className="w-full mt-2 p-2 border rounded text-sm resize-y min-h-[80px]"
          rows={3}
        />
      </div>
    </section>
  )
}

// =============================================================================
// Document List with Status Polling
// =============================================================================

function DocumentList({ documents, onRefresh }: {
  documents: DocType[]
  onRefresh: () => void
}) {
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Poll for status updates when documents are processing
  useEffect(() => {
    const hasProcessing = documents.some(
      (d) => d.processing_status === 'pending' || d.processing_status === 'processing'
    )

    if (hasProcessing) {
      pollingRef.current = setInterval(() => {
        onRefresh()
      }, 3000)
    }

    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current)
        pollingRef.current = null
      }
    }
  }, [documents, onRefresh])

  const handleDelete = async (doc: DocType) => {
    if (!confirm(`Dokument "${doc.original_name}" wirklich löschen?`)) return
    await documentsApi.delete(doc.id)
    onRefresh()
  }

  const statusLabel = (status: DocType['processing_status']) => {
    switch (status) {
      case 'completed': return 'Verarbeitet'
      case 'error': return 'Fehler'
      case 'processing': return 'Wird verarbeitet...'
      case 'pending': return 'Wartend'
    }
  }

  const statusColor = (status: DocType['processing_status']) => {
    switch (status) {
      case 'completed': return 'text-green-600'
      case 'error': return 'text-red-600'
      default: return 'text-yellow-600'
    }
  }

  return (
    <section className="mb-8">
      <h3 className="font-semibold mb-3">Dokumente ({documents.length})</h3>
      {documents.length === 0 && (
        <p className="text-sm text-gray-400">Noch keine Dokumente hochgeladen.</p>
      )}
      <div className="space-y-2">
        {documents.map((doc) => (
          <div key={doc.id} className="flex items-center gap-3 p-3 bg-white border rounded-lg">
            <div className="flex-1">
              <div className="font-medium text-sm">{doc.original_name}</div>
              <div className="text-xs text-gray-400">
                {(doc.file_size_bytes / 1024 / 1024).toFixed(1)} MB &middot; {doc.chunk_count} Chunks &middot;{' '}
                <span className={statusColor(doc.processing_status)}>
                  {statusLabel(doc.processing_status)}
                </span>
              </div>
              {doc.processing_status === 'error' && doc.processing_error && (
                <div className="text-xs text-red-500 mt-1">{doc.processing_error}</div>
              )}
              {(doc.processing_status === 'pending' || doc.processing_status === 'processing') && (
                <div className="mt-1">
                  <div className="w-32 bg-gray-200 rounded-full h-1.5">
                    <div className="bg-yellow-500 h-1.5 rounded-full animate-pulse" style={{ width: '60%' }} />
                  </div>
                </div>
              )}
            </div>
            <button
              onClick={() => handleDelete(doc)}
              className="text-red-500 hover:text-red-700 text-sm"
            >
              Löschen
            </button>
          </div>
        ))}
      </div>
    </section>
  )
}

// =============================================================================
// Glossary Section
// =============================================================================

interface GlossaryFormData {
  term: string
  definition: string
  abbreviation: string
}

const emptyGlossaryForm: GlossaryFormData = { term: '', definition: '', abbreviation: '' }

function GlossarySection({ collectionId, glossary, onRefresh }: {
  collectionId: number
  glossary: GlossaryEntry[]
  onRefresh: () => void
}) {
  const [showForm, setShowForm] = useState(false)
  const [editingEntry, setEditingEntry] = useState<GlossaryEntry | null>(null)
  const [formData, setFormData] = useState<GlossaryFormData>(emptyGlossaryForm)
  const [saving, setSaving] = useState(false)
  const [extracting, setExtracting] = useState(false)
  const [error, setError] = useState('')

  const openCreate = () => {
    setEditingEntry(null)
    setFormData(emptyGlossaryForm)
    setError('')
    setShowForm(true)
  }

  const openEdit = (entry: GlossaryEntry) => {
    setEditingEntry(entry)
    setFormData({
      term: entry.term,
      definition: entry.definition,
      abbreviation: entry.abbreviation || '',
    })
    setError('')
    setShowForm(true)
  }

  const handleSave = async () => {
    if (!formData.term || !formData.definition) {
      setError('Begriff und Definition sind erforderlich')
      return
    }
    setSaving(true)
    setError('')
    try {
      const data = {
        term: formData.term,
        definition: formData.definition,
        abbreviation: formData.abbreviation || undefined,
      }
      if (editingEntry) {
        await collectionsApi.updateGlossaryEntry(collectionId, editingEntry.id, data)
      } else {
        await collectionsApi.addGlossaryEntry(collectionId, data)
      }
      setShowForm(false)
      onRefresh()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Fehler beim Speichern')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (entry: GlossaryEntry) => {
    if (!confirm(`Glossar-Eintrag "${entry.term}" wirklich löschen?`)) return
    try {
      await collectionsApi.deleteGlossaryEntry(collectionId, entry.id)
      onRefresh()
    } catch {
      setError('Fehler beim Löschen')
    }
  }

  const handleAutoExtract = async () => {
    if (!confirm('Automatische Glossar-Extraktion starten? Dies kann einige Sekunden dauern.')) return
    setExtracting(true)
    setError('')
    try {
      await collectionsApi.autoExtractGlossary(collectionId)
      onRefresh()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Fehler bei der automatischen Extraktion')
    } finally {
      setExtracting(false)
    }
  }

  return (
    <section>
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold">Glossar ({glossary.length} Einträge)</h3>
        <div className="flex gap-2">
          <button
            onClick={handleAutoExtract}
            disabled={extracting}
            className="px-3 py-1.5 border border-atlas-300 text-atlas-700 rounded text-xs hover:bg-atlas-50 disabled:opacity-50"
          >
            {extracting ? 'Extrahiere...' : 'Auto-Extraktion'}
          </button>
          <button
            onClick={openCreate}
            className="px-3 py-1.5 bg-atlas-600 text-white rounded text-xs hover:bg-atlas-700"
          >
            Eintrag hinzufügen
          </button>
        </div>
      </div>

      <p className="text-xs text-gray-500 mb-3">
        Definieren Sie Fachbegriffe und Abkürzungen, die in den Dokumenten dieser Collection vorkommen.
        Diese werden beim Embedding automatisch als Kontext hinzugefügt.
      </p>

      {error && <div className="bg-red-50 text-red-600 p-3 rounded text-sm mb-3">{error}</div>}

      {glossary.length === 0 && (
        <p className="text-sm text-gray-400">Noch keine Glossar-Einträge vorhanden.</p>
      )}

      <div className="space-y-1">
        {glossary.map((entry) => (
          <div key={entry.id} className="flex items-center gap-2 p-2 bg-white border rounded text-sm group">
            <div className="flex-1 flex items-center gap-2">
              <span className="font-mono font-medium text-atlas-700">{entry.term}</span>
              {entry.abbreviation && <span className="text-gray-400">({entry.abbreviation})</span>}
              <span className="text-gray-600">&mdash; {entry.definition}</span>
            </div>
            <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition">
              <button
                onClick={() => openEdit(entry)}
                className="text-atlas-600 hover:text-atlas-800 text-xs"
              >
                Bearbeiten
              </button>
              <button
                onClick={() => handleDelete(entry)}
                className="text-red-500 hover:text-red-700 text-xs"
              >
                Löschen
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Glossar-Formular Dialog */}
      {showForm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-md">
            <h3 className="text-lg font-semibold mb-4">
              {editingEntry ? 'Glossar-Eintrag bearbeiten' : 'Neuer Glossar-Eintrag'}
            </h3>
            {error && <div className="bg-red-50 text-red-600 p-3 rounded text-sm mb-4">{error}</div>}
            <div className="space-y-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Begriff</label>
                <input
                  type="text"
                  value={formData.term}
                  onChange={(e) => setFormData({ ...formData, term: e.target.value })}
                  placeholder="z.B. Ausführungsklasse"
                  className="w-full p-2 border rounded text-sm focus:ring-2 focus:ring-atlas-500 outline-none"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Abkürzung (optional)</label>
                <input
                  type="text"
                  value={formData.abbreviation}
                  onChange={(e) => setFormData({ ...formData, abbreviation: e.target.value })}
                  placeholder="z.B. EXC"
                  className="w-full p-2 border rounded text-sm focus:ring-2 focus:ring-atlas-500 outline-none"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Definition</label>
                <textarea
                  value={formData.definition}
                  onChange={(e) => setFormData({ ...formData, definition: e.target.value })}
                  placeholder="Kurze Erklärung des Begriffs..."
                  rows={3}
                  className="w-full p-2 border rounded text-sm focus:ring-2 focus:ring-atlas-500 outline-none resize-none"
                />
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-6">
              <button
                onClick={() => setShowForm(false)}
                className="px-4 py-2 border rounded text-sm text-gray-600 hover:bg-gray-50"
              >
                Abbrechen
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-4 py-2 bg-atlas-600 text-white rounded text-sm hover:bg-atlas-700 disabled:opacity-50"
              >
                {saving ? 'Speichern...' : 'Speichern'}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
