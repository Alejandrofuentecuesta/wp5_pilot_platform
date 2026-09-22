"use client"

import { useEffect, useRef, useState } from "react"

interface ExitConfirmationModalProps {
  onConfirm: (reason: string) => void
  onClose: () => void
}

const exitReasons = [
  "Porque la conversación me ha resultado demasiado hostil",
  "Porque la conversación me ha resultado demasiado monótona",
  "Porque estoy aburrido",
  "Porque no tengo tiempo",
] as const

export default function ExitConfirmationModal({
  onConfirm,
  onClose,
}: ExitConfirmationModalProps) {
  const modalRef = useRef<HTMLDivElement>(null)
  const [selectedReason, setSelectedReason] = useState("")
  const [otherReason, setOtherReason] = useState("")

  // Focus trap and Escape handling
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    document.addEventListener("keydown", handleKey)
    return () => document.removeEventListener("keydown", handleKey)
  }, [onClose])

  const isOther = selectedReason === "Otros"
  const canConfirm = isOther ? otherReason.trim().length > 0 : selectedReason.length > 0
  const submitReason = isOther ? `Otros: ${otherReason.trim()}` : selectedReason

  return (
    <div
      className="fixed inset-0 bg-black/40 flex items-center justify-center z-[9999] px-4"
      role="dialog"
      aria-modal="true"
      aria-label="Confirmar salida"
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
          <p className="text-sm text-secondary leading-relaxed mb-4">
            ¿Estás seguro de querer salir del experimento? Después no podrás volver a entrar.
          </p>
          <p className="mb-4 rounded-lg border border-danger/30 bg-danger/5 px-3 py-2.5 text-sm font-semibold leading-relaxed text-danger">
            Si sales ahora, tu participación quedará incompleta y perderás la compensación económica.
          </p>
          <label className="block text-sm font-medium text-primary mb-1.5">
            ¿Por qué quieres salir? <span className="text-danger">*</span>
          </label>
          <div className="space-y-2" role="radiogroup" aria-label="Motivo de salida">
            {[...exitReasons, "Otros"].map((option) => (
              <label
                key={option}
                className="flex cursor-pointer items-start gap-2 rounded-lg border border-border bg-bg-surface px-3 py-2 text-sm text-primary transition-colors hover:border-accent/60"
              >
                <input
                  type="radio"
                  name="exit-reason"
                  value={option}
                  checked={selectedReason === option}
                  onChange={() => setSelectedReason(option)}
                  className="mt-0.5 accent-accent"
                />
                <span>{option}</span>
              </label>
            ))}
          </div>
          {isOther && (
            <textarea
              value={otherReason}
              onChange={(e) => setOtherReason(e.target.value)}
              autoFocus
              rows={3}
              placeholder="Cuéntanos brevemente el motivo…"
              className="mt-3 w-full rounded-lg border border-border bg-bg-surface px-3 py-2 text-sm text-primary resize-none placeholder:text-tertiary focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent/20"
            />
          )}
          {!canConfirm && (
            <p className="text-xs text-tertiary mt-1.5">
              Por favor, selecciona un motivo antes de salir.
            </p>
          )}
        </div>
        <div className="flex justify-end gap-2 px-6 pb-5">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm rounded-lg border border-border text-secondary hover:bg-gray-50 transition-colors cursor-pointer"
          >
            Cancelar
          </button>
          <button
            onClick={() => onConfirm(submitReason)}
            disabled={!canConfirm}
            className="px-4 py-2 text-sm rounded-lg bg-danger hover:bg-red-700 text-white transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Aceptar
          </button>
        </div>
      </div>
    </div>
  )
}
