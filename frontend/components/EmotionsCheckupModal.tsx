"use client"

import { useState, useEffect, useRef } from "react"

interface EmotionsCheckupModalProps {
  onSubmit: (emotion: string, temptedToReport: boolean, reportedUsers?: string[]) => void
  participants: string[]
}

export default function EmotionsCheckupModal({ onSubmit, participants }: EmotionsCheckupModalProps) {
  const [selectedEmotion, setSelectedEmotion] = useState<string | null>(null)
  const [selectedTempted, setSelectedTempted] = useState<boolean | null>(null)
  const [customEmotion, setCustomEmotion] = useState<string>("")
  const [selectedReportedUsers, setSelectedReportedUsers] = useState<string[]>([])
  const modalRef = useRef<HTMLDivElement>(null)

  // Focus management
  useEffect(() => {
    if (modalRef.current) {
      modalRef.current.focus()
    }
  }, [])

  const emotions = [
    { value: "Enfadado/a", label: "Enfadado/a", emoji: "😡" },
    { value: "contento/a", label: "Contento/a", emoji: "😊" },
    { value: "asustado/a", label: "Asustado/a", emoji: "😨" },
    { value: "Otra", label: "Otra", emoji: "💭" },
  ]

  const handleSubmit = () => {
    if (isFormValid) {
      const finalEmotion = selectedEmotion === "Otra" ? `Otra: ${customEmotion.trim()}` : selectedEmotion!
      onSubmit(
        finalEmotion,
        selectedTempted!,
        selectedTempted ? selectedReportedUsers : undefined
      )
    }
  }

  const isFormValid =
    selectedEmotion !== null &&
    (selectedEmotion !== "Otra" || customEmotion.trim().length > 0) &&
    selectedTempted !== null &&
    (selectedTempted === false || selectedReportedUsers.length > 0 || participants.length === 0)

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-[9999] px-4 py-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="emotions-checkup-title"
    >
      <div
        ref={modalRef}
        tabIndex={-1}
        className="bg-white rounded-2xl w-full max-w-[500px] shadow-2xl border border-border overflow-hidden focus:outline-none animate-in fade-in zoom-in-95 duration-200"
      >
        <div className="h-1.5 bg-accent" />
        
        <div className="p-6 space-y-6">
          <div className="space-y-1 text-center">
            <h3 id="emotions-checkup-title" className="text-xl font-bold text-primary">
              Chequeo de estado de ánimo
            </h3>
            <p className="text-xs text-secondary">
              Por favor, responde a estas breves preguntas sobre tu experiencia actual.
            </p>
          </div>

          {/* Question 1: How do you feel? */}
          <div className="space-y-3">
            <label className="block text-sm font-semibold text-primary">
              1. ¿Cómo te sientes en este momento?
            </label>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
              {emotions.map((emotion) => {
                const isSelected = selectedEmotion === emotion.value
                return (
                  <button
                    key={emotion.value}
                    type="button"
                    onClick={() => setSelectedEmotion(emotion.value)}
                    className={`flex flex-col items-center justify-center p-3 rounded-xl border text-sm font-medium transition-all ${
                      isSelected
                        ? "border-accent bg-accent-soft text-accent ring-2 ring-accent/30"
                        : "border-border text-secondary hover:border-accent-hover hover:bg-bg-feed"
                    }`}
                  >
                    <span className="text-2xl mb-1.5" role="img" aria-label={emotion.label}>
                      {emotion.emoji}
                    </span>
                    <span>{emotion.label}</span>
                  </button>
                )
              })}
            </div>

            {selectedEmotion === "Otra" && (
              <div className="mt-3 space-y-1.5 animate-in fade-in slide-in-from-top-1 duration-150">
                <label className="block text-xs font-semibold text-secondary">
                  Especifica otra emoción:
                </label>
                <input
                  type="text"
                  value={customEmotion}
                  onChange={(e) => setCustomEmotion(e.target.value)}
                  placeholder="¿Cómo te sientes?"
                  className="w-full px-3 py-2 text-sm rounded-xl border border-border focus:border-accent focus:ring-1 focus:ring-accent/20 outline-none"
                  maxLength={50}
                />
              </div>
            )}
          </div>

          {/* Question 2: Tempted to report? */}
          <div className="space-y-3">
            <label className="block text-sm font-semibold text-primary">
              2. ¿Has tenido la tentación de reportar a algún usuario de la plataforma?
            </label>
            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setSelectedTempted(true)}
                className={`p-3 rounded-xl border text-sm font-medium transition-all text-center ${
                  selectedTempted === true
                    ? "border-accent bg-accent-soft text-accent ring-2 ring-accent/30"
                    : "border-border text-secondary hover:border-accent-hover hover:bg-bg-feed"
                }`}
              >
                Sí, lo he pensado
              </button>
              <button
                type="button"
                onClick={() => setSelectedTempted(false)}
                className={`p-3 rounded-xl border text-sm font-medium transition-all text-center ${
                  selectedTempted === false
                    ? "border-accent bg-accent-soft text-accent ring-2 ring-accent/30"
                    : "border-border text-secondary hover:border-accent-hover hover:bg-bg-feed"
                }`}
              >
                No, en absoluto
              </button>
            </div>

            {selectedTempted === true && (
              <div className="mt-3 space-y-2 animate-in fade-in slide-in-from-top-1 duration-150">
                <label className="block text-xs font-semibold text-secondary">
                  ¿A quién? (Puedes seleccionar varios)
                </label>
                {participants.length === 0 ? (
                  <p className="text-xs text-secondary italic">No hay otros participantes en la sesión todavía.</p>
                ) : (
                  <div className="max-h-40 overflow-y-auto border border-border rounded-xl p-3 space-y-2 bg-bg-surface">
                    {participants.map((name) => {
                      const isChecked = selectedReportedUsers.includes(name)
                      return (
                        <label
                          key={name}
                          className="flex items-center gap-2 text-sm font-medium text-primary cursor-pointer select-none"
                        >
                          <input
                            type="checkbox"
                            checked={isChecked}
                            onChange={() => {
                              setSelectedReportedUsers((prev) =>
                                isChecked
                                  ? prev.filter((n) => n !== name)
                                  : [...prev, name]
                              )
                            }}
                            className="rounded border-border text-accent focus:ring-accent w-4 h-4"
                          />
                          <span>{name}</span>
                        </label>
                      )
                    })}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Reminder box */}
          <div className="rounded-xl bg-bg-feed border border-border/60 p-4 flex gap-3 items-start">
            <svg
              className="w-5 h-5 text-accent shrink-0 mt-0.5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              xmlns="http://www.w3.org/2000/svg"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
            <p className="text-xs leading-relaxed text-secondary">
              <strong>Recordatorio:</strong> Si consideras inapropiado o molesto algún comentario, puedes reportarlo o bloquear al usuario directamente usando el botón <strong>&quot;Report&quot;</strong> que aparece debajo de su mensaje.
            </p>
          </div>
        </div>

        {/* Submit button */}
        <div className="bg-bg-feed px-6 py-4 flex justify-end border-t border-border">
          <button
            onClick={handleSubmit}
            disabled={!isFormValid}
            className="w-full sm:w-auto px-6 py-2.5 text-sm font-semibold rounded-xl text-white bg-accent hover:bg-accent-hover transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Enviar y continuar
          </button>
        </div>
      </div>
    </div>
  )
}
