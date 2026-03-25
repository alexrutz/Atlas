/**
 * DocumentsPage - Dokumentenverwaltung mit Upload.
 *
 * Layout:
 * - Left sidebar: Collection-Liste
 * - Main area: Two columns
 *   - Left column: Upload + Dokumentenliste
 *   - Right column: Collection-Kontext (große Textarea)
 */

import { useEffect, useState, useCallback, useRef } from 'react'
import { useDropzone } from 'react-dropzone'
import { collectionsApi, documentsApi } from '../services/api'
import type { Collection, Document as DocType } from '../types'

export default function DocumentsPage() {
  const [collections, setCollections] = useState<Collection[]>([])
  const [selectedCollection, setSelectedCollection] = useState<Collection | null>(null)
  const [documents, setDocuments] = useState<DocType[]>([])
  const [contextDraft, setContextDraft] = useState('')
  const [contextSaving, setContextSaving] = useState(false)

  const loadCollections = useCallback(async () => {
    const data = await collectionsApi.list()
    setCollections(data)
  }, [])

  useEffect(() => {
    loadCollections()
  }, [loadCollections])

  useEffect(() => {
    if (selectedCollection) {
      setContextDraft(selectedCollection.context_text || '')
    }
  }, [selectedCollection])

  const loadDocuments = useCallback(async () => {
    if (!selectedCollection) return
    const docs = await documentsApi.list(selectedCollection.id)
    setDocuments(docs)
  }, [selectedCollection])

  useEffect(() => {
    loadDocuments()
  }, [loadDocuments])

  const handleSaveContext = useCallback(async () => {
    if (!selectedCollection) return
    setContextSaving(true)
    try {
      await collectionsApi.update(selectedCollection.id, { context_text: contextDraft })
      setSelectedCollection({ ...selectedCollection, context_text: contextDraft })
      setCollections((prev) => prev.map((c) =>
        c.id === selectedCollection.id ? { ...c, context_text: contextDraft } : c
      ))
    } finally {
      setContextSaving(false)
    }
  }, [selectedCollection, contextDraft])

  return (
    <div className="flex h-full">
      {/* Collection-Liste */}
      <div className="w-64 border-r bg-white p-4 overflow-y-auto shrink-0 flex flex-col">
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
            <div className="flex items-center gap-1">
              <span className="font-medium text-sm">{col.name}</span>
              {col.context_text && <span className="w-1.5 h-1.5 rounded-full bg-atlas-500 shrink-0" />}
            </div>
            <div className="text-xs text-gray-400">{col.document_count} Dokumente</div>
          </button>
        ))}
      </div>

      {/* Hauptbereich */}
      <div className="flex-1 overflow-y-auto min-w-0">
        {!selectedCollection ? (
          <div className="text-center text-gray-400 mt-20">
            Wählen Sie eine Collection aus der Liste.
          </div>
        ) : (
          <div className="flex h-full">
            {/* Linke Spalte: Upload + Dokumentenliste */}
            <div className="flex-1 p-6 overflow-y-auto border-r">
              <h2 className="text-xl font-bold mb-4">{selectedCollection.name}</h2>
              {selectedCollection.description && (
                <p className="text-gray-600 mb-6">{selectedCollection.description}</p>
              )}

              <UploadSection
                collectionId={selectedCollection.id}
                onUploadComplete={() => { loadDocuments(); loadCollections() }}
              />

              <div className="mt-6">
                <DocumentList
                  documents={documents}
                  onRefresh={loadDocuments}
                />
              </div>
            </div>

            {/* Rechte Spalte: Collection-Kontext */}
            <div className="flex-1 p-6 flex flex-col">
              <h3 className="font-semibold mb-2 text-sm">Collection-Kontext</h3>
              <p className="text-xs text-gray-400 mb-3">
                Variablen, Abkürzungen und Fachbegriffe für die Suchanreicherung.
              </p>
              <textarea
                value={contextDraft}
                onChange={(e) => setContextDraft(e.target.value)}
                placeholder="z.B. L1 = Kühlerlänge, B2 = Gehäusebreite..."
                className="flex-1 w-full text-sm p-3 border rounded-lg resize-none focus:ring-2 focus:ring-atlas-500 outline-none"
              />
              <button
                onClick={handleSaveContext}
                disabled={contextSaving || contextDraft === (selectedCollection.context_text || '')}
                className="mt-2 w-full px-3 py-2 text-sm bg-atlas-600 text-white rounded-lg hover:bg-atlas-700 disabled:opacity-50 transition"
              >
                {contextSaving ? 'Speichern...' : 'Kontext speichern'}
              </button>
            </div>
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
          collectionId, file,
          (percent) => setUploadProgress(percent),
        )
        setUploadSuccess(`"${file.name}" erfolgreich hochgeladen.`)
        onUploadComplete()
      } catch (err: unknown) {
        const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        setUploadError(msg || `Fehler beim Hochladen von "${file.name}"`)
      } finally {
        setUploading(false)
        setUploadProgress(0)
      }
    }
  }, [collectionId, onUploadComplete])

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
    <section>
      <h3 className="font-semibold mb-3 text-sm">Dokument hochladen</h3>

      {uploadError && <div className="bg-red-50 text-red-600 p-2 rounded text-xs mb-2">{uploadError}</div>}
      {uploadSuccess && <div className="bg-green-50 text-green-600 p-2 rounded text-xs mb-2">{uploadSuccess}</div>}

      <div
        {...getRootProps()}
        className={`border-2 border-dashed rounded-lg p-6 text-center transition cursor-pointer min-h-[120px] flex items-center justify-center ${
          isDragActive
            ? 'border-atlas-500 bg-atlas-50'
            : uploading
            ? 'border-gray-200 bg-gray-50 cursor-not-allowed'
            : 'border-gray-300 hover:border-atlas-400'
        }`}
      >
        <input {...getInputProps()} />
        {uploading ? (
          <div className="w-full">
            <p className="text-gray-600 text-sm mb-2">Hochladen... {uploadProgress}%</p>
            <div className="w-full bg-gray-200 rounded-full h-2">
              <div className="bg-atlas-600 h-2 rounded-full transition-all" style={{ width: `${uploadProgress}%` }} />
            </div>
          </div>
        ) : isDragActive ? (
          <p className="text-atlas-600 font-medium">Datei hier ablegen...</p>
        ) : (
          <div>
            <p className="text-gray-500 text-sm">Datei hierher ziehen oder klicken</p>
            <p className="text-xs text-gray-400 mt-1">PDF, DOCX, XLSX, PPTX, TXT, CSV, HTML (max. 100 MB)</p>
          </div>
        )}
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

  useEffect(() => {
    const hasProcessing = documents.some(
      (d) => d.processing_status === 'pending' || d.processing_status === 'processing'
    )
    if (hasProcessing) {
      pollingRef.current = setInterval(() => { onRefresh() }, 3000)
    }
    return () => {
      if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null }
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
    <section>
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
            <button onClick={() => handleDelete(doc)} className="text-red-500 hover:text-red-700 text-sm">
              Löschen
            </button>
          </div>
        ))}
      </div>
    </section>
  )
}
