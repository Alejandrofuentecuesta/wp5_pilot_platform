"use client"

import { useEffect, useRef } from "react"

interface ReportModalProps {
  senderName: string
  reporting: boolean
  onReport: () => void
  onReportAndBlock: () => void
  onClose: () => void
}

export default function ReportModal({
  senderName,
  reporting,
  onReport,
  onReportAndBlock,
  onClose,
}: ReportModalProps) {
  const modalRef = useRef<HTMLDivElement>(null)

  // Focus trap and Escape handling
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !reporting) onClose()
    }
    document.addEventListener("keydown", handleKey)
    return () => document.removeEventListener("keydown", handleKey)
  }, [onClose, reporting])

  return (
    <div
      className="fixed inset-0 bg-black/40 flex items-center justify-center z-[9999] px-4"
      role="dialog"
      aria-modal="true"
      aria-label="Reportar mensaje"
      onClick={(e) => {
        if (e.target === e.currentTarget && !reporting) onClose()
      }}
    >
      <div
        ref={modalRef}
        className="bg-white rounded-xl w-full max-w-[420px] shadow-2xl overflow-hidden"
      >
        <div className="px-6 pt-5 pb-4">
          <h3 className="text-lg font-semibold text-primary m-0 mb-2">
            Reportar mensaje
          </h3>
          <p className="text-sm text-secondary leading-relaxed">
            Puedes reportar este mensaje. ¿También quieres dejar de ver todos
            los mensajes de <strong className="text-primary">{senderName}</strong>?
          </p>
        </div>
        <div className="flex justify-end gap-2 px-6 pb-5">
          <button
            onClick={onClose}
            disabled={reporting}
            className="px-4 py-2 text-sm rounded-lg border border-border text-secondary hover:bg-gray-50 transition-colors disabled:opacity-50"
          >
            Cancelar
          </button>
          <button
            onClick={onReport}
            disabled={reporting}
            className="px-4 py-2 text-sm rounded-lg border border-border text-primary hover:bg-gray-50 transition-colors disabled:opacity-50"
          >
            Reportar
          </button>
          <button
            onClick={onReportAndBlock}
            disabled={reporting}
            className="px-4 py-2 text-sm rounded-lg bg-danger text-white hover:bg-red-700 transition-colors disabled:opacity-50"
          >
            Reportar y bloquear
          </button>
        </div>
      </div>
    </div>
  )
}
