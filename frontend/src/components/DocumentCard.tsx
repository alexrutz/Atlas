/**
 * DocumentCard - Klickbare Dokumentkarte in der Chat-Nachricht.
 *
 * Wird angezeigt, wenn der "gib mir"-Agent ein Dokument liefert.
 * Klick öffnet den PDF-Viewer.
 */

import { useState } from 'react'
import type { DocumentDelivery } from '../types'
import PdfViewer from './PdfViewer'

interface DocumentCardProps {
  delivery: DocumentDelivery
}

export default function DocumentCard({ delivery }: DocumentCardProps) {
  const [viewerOpen, setViewerOpen] = useState(false)

  const fileIcon = delivery.file_type === '.pdf' ? (
    <svg className="w-8 h-8 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
    </svg>
  ) : (
    <svg className="w-8 h-8 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
    </svg>
  )

  return (
    <>
      <button
        onClick={() => setViewerOpen(true)}
        className="mt-3 w-full flex items-center gap-4 p-4 bg-gradient-to-r from-atlas-50 to-white border-2 border-atlas-200 rounded-xl hover:border-atlas-400 hover:shadow-md transition-all group cursor-pointer text-left"
      >
        <div className="flex-shrink-0 flex items-center justify-center w-14 h-14 rounded-lg bg-white border border-gray-200 shadow-sm group-hover:shadow-md transition">
          {fileIcon}
        </div>
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-gray-800 truncate group-hover:text-atlas-700 transition">
            {delivery.document_name}
          </p>
          <p className="text-xs text-gray-500 mt-0.5">
            {delivery.collection_name}
            {delivery.page_count > 1 && (
              <span className="ml-2">{delivery.page_count} Seiten</span>
            )}
          </p>
        </div>
        <div className="flex-shrink-0 flex items-center gap-1 text-atlas-600 text-xs font-medium opacity-0 group-hover:opacity-100 transition">
          <span>Öffnen</span>
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
          </svg>
        </div>
      </button>

      {viewerOpen && (
        <PdfViewer
          delivery={delivery}
          onClose={() => setViewerOpen(false)}
        />
      )}
    </>
  )
}
