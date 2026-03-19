/**
 * PdfViewer - Modal-basierter PDF-Viewer mit seitenweiser Anzeige.
 *
 * Lädt jede Seite als PNG über authentifizierten Fetch vom Backend.
 * Navigation mit Vor/Zurück-Buttons, Download-Button, Tastatursteuerung.
 */

import { useState, useEffect, useCallback } from 'react'
import { documentsApi } from '../services/api'
import type { DocumentDelivery } from '../types'

interface PdfViewerProps {
  delivery: DocumentDelivery
  onClose: () => void
}

export default function PdfViewer({ delivery, onClose }: PdfViewerProps) {
  const [currentPage, setCurrentPage] = useState(1)
  const [pageCount, setPageCount] = useState(delivery.page_count || 1)
  const [loading, setLoading] = useState(true)
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [imageError, setImageError] = useState(false)

  useEffect(() => {
    documentsApi.getPageCount(delivery.document_id).then((data) => {
      setPageCount(data.page_count)
    }).catch(() => {})
  }, [delivery.document_id])

  // Fetch page image with auth header
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setImageError(false)
    setImageUrl(null)

    const token = localStorage.getItem('atlas_token')
    const url = documentsApi.getPageImageUrl(delivery.document_id, currentPage)

    fetch(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((res) => {
        if (!res.ok) throw new Error('Failed to load page')
        return res.blob()
      })
      .then((blob) => {
        if (cancelled) return
        const objectUrl = URL.createObjectURL(blob)
        setImageUrl(objectUrl)
        setLoading(false)
      })
      .catch(() => {
        if (cancelled) return
        setLoading(false)
        setImageError(true)
      })

    return () => {
      cancelled = true
      if (imageUrl) URL.revokeObjectURL(imageUrl)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [delivery.document_id, currentPage])

  const handleDownload = useCallback(() => {
    const token = localStorage.getItem('atlas_token')
    const downloadUrl = documentsApi.getDownloadUrl(delivery.document_id)
    fetch(downloadUrl, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((res) => res.blob())
      .then((blob) => {
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = delivery.document_name
        a.click()
        URL.revokeObjectURL(url)
      })
  }, [delivery.document_id, delivery.document_name])

  // Keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'ArrowLeft' && currentPage > 1) setCurrentPage((p) => p - 1)
      if (e.key === 'ArrowRight' && currentPage < pageCount) setCurrentPage((p) => p + 1)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose, currentPage, pageCount])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="bg-white rounded-xl shadow-2xl flex flex-col max-w-5xl w-full mx-4 max-h-[95vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200 bg-gray-50 rounded-t-xl">
          <div className="flex items-center gap-3 min-w-0">
            <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-red-100">
              <svg className="w-5 h-5 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
              </svg>
            </div>
            <div className="min-w-0">
              <h3 className="font-semibold text-gray-800 truncate text-sm">{delivery.document_name}</h3>
              <p className="text-xs text-gray-500">{delivery.collection_name}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleDownload}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-atlas-700 bg-atlas-50 hover:bg-atlas-100 rounded-lg transition"
              title="Herunterladen"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              Download
            </button>
            <button
              onClick={onClose}
              className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition"
              title="Schliessen (Esc)"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Page content */}
        <div className="flex-1 overflow-auto bg-gray-100 flex items-center justify-center p-4 min-h-0 relative" style={{ minHeight: '60vh' }}>
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center bg-gray-100/80 z-10">
              <div className="flex items-center gap-2 text-gray-500">
                <div className="w-5 h-5 border-2 border-gray-300 border-t-atlas-500 rounded-full animate-spin" />
                <span className="text-sm">Seite wird geladen...</span>
              </div>
            </div>
          )}
          {imageError ? (
            <div className="text-center text-gray-500">
              <svg className="w-12 h-12 mx-auto mb-2 text-gray-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
              </svg>
              <p className="text-sm">Seite konnte nicht geladen werden</p>
            </div>
          ) : imageUrl ? (
            <img
              src={imageUrl}
              alt={`Seite ${currentPage}`}
              className="max-h-full max-w-full object-contain shadow-lg rounded"
            />
          ) : null}
        </div>

        {/* Footer / Navigation */}
        <div className="flex items-center justify-between px-5 py-3 border-t border-gray-200 bg-gray-50 rounded-b-xl">
          <button
            onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
            disabled={currentPage <= 1}
            className="flex items-center gap-1 px-3 py-1.5 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-30 disabled:cursor-not-allowed transition"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
            Zurück
          </button>

          <span className="text-sm text-gray-600 font-medium">
            Seite {currentPage} von {pageCount}
          </span>

          <button
            onClick={() => setCurrentPage((p) => Math.min(pageCount, p + 1))}
            disabled={currentPage >= pageCount}
            className="flex items-center gap-1 px-3 py-1.5 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-30 disabled:cursor-not-allowed transition"
          >
            Weiter
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  )
}
