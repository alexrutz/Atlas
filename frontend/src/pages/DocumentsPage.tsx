/**
 * DocumentsPage - Dokumentenverwaltung mit Upload, Kontext-Editor und Glossar.
 *
 * Hier können Benutzer:
 * - Dokumente zu Collections hochladen
 * - Kontext-Beschreibungen hinzufügen (WICHTIG für Context-Enriched Embedding)
 * - Glossar-Einträge verwalten
 * - Den Verarbeitungsstatus einsehen
 */

import { useEffect, useState } from 'react'
import { collectionsApi, documentsApi } from '../services/api'
import type { Collection, Document as DocType, GlossaryEntry } from '../types'

export default function DocumentsPage() {
  const [collections, setCollections] = useState<Collection[]>([])
  const [selectedCollection, setSelectedCollection] = useState<Collection | null>(null)
  const [documents, setDocuments] = useState<DocType[]>([])
  const [glossary, setGlossary] = useState<GlossaryEntry[]>([])

  useEffect(() => {
    collectionsApi.list().then(setCollections)
  }, [])

  useEffect(() => {
    if (selectedCollection) {
      documentsApi.list(selectedCollection.id).then(setDocuments)
      collectionsApi.getGlossary(selectedCollection.id).then(setGlossary)
    }
  }, [selectedCollection])

  return (
    <div className="flex h-full">
      {/* Collection-Liste */}
      <div className="w-64 border-r bg-white p-4 overflow-y-auto">
        <h3 className="font-semibold text-sm text-gray-500 uppercase mb-3">Collections</h3>
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
            <section className="mb-8">
              <h3 className="font-semibold mb-3">Dokument hochladen</h3>
              <div className="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center hover:border-atlas-400 transition cursor-pointer">
                <p className="text-gray-500">
                  Datei hierher ziehen oder klicken zum Auswählen
                </p>
                <p className="text-xs text-gray-400 mt-1">
                  PDF, DOCX, XLSX, PPTX, TXT, CSV, HTML (max. 100 MB)
                </p>
                {/* TODO: react-dropzone Integration */}
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
                  placeholder="z.B.: Dieses Dokument ist die DIN EN 1090-2 Norm. EXC = Ausführungsklasse, WPS = Schweißanweisung..."
                  className="w-full mt-2 p-2 border rounded text-sm resize-y min-h-[80px]"
                  rows={3}
                />
              </div>
            </section>

            {/* Dokumentenliste */}
            <section className="mb-8">
              <h3 className="font-semibold mb-3">Dokumente ({documents.length})</h3>
              <div className="space-y-2">
                {documents.map((doc) => (
                  <div key={doc.id} className="flex items-center gap-3 p-3 bg-white border rounded-lg">
                    <div className="flex-1">
                      <div className="font-medium text-sm">{doc.original_name}</div>
                      <div className="text-xs text-gray-400">
                        {(doc.file_size_bytes / 1024 / 1024).toFixed(1)} MB &middot;
                        {doc.chunk_count} Chunks &middot;
                        <span className={
                          doc.processing_status === 'completed' ? 'text-green-600' :
                          doc.processing_status === 'error' ? 'text-red-600' :
                          'text-yellow-600'
                        }>
                          {doc.processing_status === 'completed' ? 'Verarbeitet' :
                           doc.processing_status === 'error' ? 'Fehler' :
                           doc.processing_status === 'processing' ? 'Wird verarbeitet...' : 'Wartend'}
                        </span>
                      </div>
                    </div>
                    <button
                      onClick={() => documentsApi.delete(doc.id).then(() => setDocuments(d => d.filter(x => x.id !== doc.id)))}
                      className="text-red-500 hover:text-red-700 text-sm"
                    >
                      Löschen
                    </button>
                  </div>
                ))}
              </div>
            </section>

            {/* Glossar */}
            <section>
              <h3 className="font-semibold mb-3">Glossar ({glossary.length} Einträge)</h3>
              <p className="text-xs text-gray-500 mb-3">
                Definieren Sie Fachbegriffe und Abkürzungen, die in den Dokumenten dieser Collection vorkommen.
                Diese werden beim Embedding automatisch als Kontext hinzugefügt.
              </p>
              <div className="space-y-1">
                {glossary.map((entry) => (
                  <div key={entry.id} className="flex items-center gap-2 p-2 bg-white border rounded text-sm">
                    <span className="font-mono font-medium text-atlas-700">{entry.term}</span>
                    {entry.abbreviation && <span className="text-gray-400">({entry.abbreviation})</span>}
                    <span className="text-gray-600">&mdash; {entry.definition}</span>
                  </div>
                ))}
              </div>
              {/* TODO: Glossar-Eintrag hinzufügen Form */}
            </section>
          </div>
        )}
      </div>
    </div>
  )
}
