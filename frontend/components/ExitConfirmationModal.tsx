"use client"

import { useEffect, useRef } from "react"

interface ExitConfirmationModalProps {
  onConfirm: () => void
  onClose: () => void
}

export default function ExitConfirmationModal({
  onConfirm,
  onClose,
}: ExitConfirmationModalProps) {
  const modalRef = useRef<HTMLDivElement>(null)

  // Focus trap and Escape handling
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    document.addEventListener("keydown", handleKey)
    return () => document.removeEventListener("keydown", handleKey)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 bg-black/40 flex items-center justify-center z-[9999] px-4"
      role="dialog"
      aria-modal="true"
      aria-label="Confirm exit"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        ref={modalRef}
        className="bg-white rounded-xl w-full max-w-[420px] shadow-2xl overflow-hidden border border-border"
      >
        <div className="px-6 pt-5 pb-4">
          <h3 className="text-lg font-semibold text-primary m-0 mb-2">
            ¿Salir del experimento?
          </h3>
          <p className="text-sm text-secondary leading-relaxed">
            ¿Estás seguro de querer salir del experimento? Después no podrás volver a entrar.
          </p>
        </div>
        <div className="flex justify-end gap-2 px-6 pb-5">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm rounded-lg border border-border text-secondary hover:bg-gray-50 transition-colors cursor-pointer"
          >
            Cancelar
          </button>
          <button
            onClick={onConfirm}
            className="px-4 py-2 text-sm rounded-lg bg-danger hover:bg-red-700 text-white transition-colors cursor-pointer"
          >
            Aceptar
          </button>
        </div>
      </div>
    </div>
  )
}
