"use client"

import { useEffect, useState } from "react"

export const REPORT_REASONS = [
  "Contiene insultos u ofensas",
  "Es hostil o ataca personalmente a alguien",
  "Contiene odio o discriminación hacia un grupo",
  "Difunde información falsa",
  "Promueve violencia o daño",
  "Me resulta molesto o incómodo",
  "No representa bien la posición que quiero defender",
  "Otro motivo",
  "No sé / no quiero contestar",
] as const

interface ReportModalProps {
  senderName: string
  reporting: boolean
  onAccept: (reasons: string[], otherReason: string | null) => void
  onClose: () => void
}

export default function ReportModal({ senderName, reporting, onAccept, onClose }: ReportModalProps) {
  const [selectedReasons, setSelectedReasons] = useState<string[]>([])
  const [otherReason, setOtherReason] = useState("")

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !reporting) onClose()
    }
    document.addEventListener("keydown", handleKey)
    return () => document.removeEventListener("keydown", handleKey)
  }, [onClose, reporting])

  const toggleReason = (reason: string) => {
    setSelectedReasons((current) =>
      current.includes(reason) ? current.filter((item) => item !== reason) : [...current, reason],
    )
  }

  return (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 px-4"
      role="dialog"
      aria-modal="true"
      aria-label="Reportar mensaje"
      onClick={(event) => {
        if (event.target === event.currentTarget && !reporting) onClose()
      }}
    >
      <div className="max-h-[90dvh] w-full max-w-[500px] overflow-y-auto rounded-xl bg-white shadow-2xl">
        <div className="px-6 pb-4 pt-5">
          <h3 className="m-0 mb-2 text-lg font-semibold text-primary">Reportar mensaje</h3>
          <p className="mb-4 text-sm leading-relaxed text-secondary">
            ¿Por qué quieres reportar el mensaje de <strong className="text-primary">{senderName}</strong>?
          </p>
          <fieldset className="space-y-2">
            <legend className="sr-only">Motivos del reporte</legend>
            {REPORT_REASONS.map((reason) => {
              const checked = selectedReasons.includes(reason)
              return (
                <label
                  key={reason}
                  className={`flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2.5 text-sm transition-colors ${checked ? "border-accent bg-accent-soft/50 text-primary" : "border-border text-secondary hover:border-accent"}`}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggleReason(reason)}
                    className="mt-0.5 h-4 w-4 rounded border-border text-accent focus:ring-accent"
                  />
                  <span>{reason}</span>
                </label>
              )
            })}
          </fieldset>
          {selectedReasons.includes("Otro motivo") && (
            <textarea
              rows={3}
              maxLength={1000}
              value={otherReason}
              onChange={(event) => setOtherReason(event.target.value)}
              placeholder="Especifica brevemente el motivo..."
              className="mt-3 w-full resize-y rounded-lg border border-border px-3 py-2 text-sm text-primary outline-none focus:border-accent focus:ring-1 focus:ring-accent/20"
            />
          )}
        </div>
        <div className="flex justify-end gap-2 px-6 pb-5">
          <button
            onClick={onClose}
            disabled={reporting}
            className="rounded-lg border border-border px-4 py-2 text-sm text-secondary transition-colors hover:bg-gray-50 disabled:opacity-50"
          >
            Cancelar
          </button>
          <button
            onClick={() => onAccept(selectedReasons, otherReason.trim() || null)}
            disabled={reporting || selectedReasons.length === 0 || (selectedReasons.includes("Otro motivo") && !otherReason.trim())}
            className="rounded-lg bg-danger px-4 py-2 text-sm text-white transition-colors hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {reporting ? "Enviando..." : "Aceptar"}
          </button>
        </div>
      </div>
    </div>
  )
}
