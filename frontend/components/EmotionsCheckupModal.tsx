"use client"

import { useState, useEffect, useRef } from "react"

const MAX_CUSTOM_EMOTION_LENGTH = 300

interface EmotionRating {
  emotion: string
  intensity: number
}

interface EmotionsCheckupModalProps {
  onSubmit: (emotions: EmotionRating[], temptedToReport: boolean, reportedUsers?: string[]) => void
  participants: string[]
}

const INTENSITY_SCALE = [1, 2, 3, 4, 5]

export default function EmotionsCheckupModal({ onSubmit, participants }: EmotionsCheckupModalProps) {
  const [selectedEmotions, setSelectedEmotions] = useState<string[]>([])
  const [intensities, setIntensities] = useState<Record<string, number>>({})
  const [selectedTempted, setSelectedTempted] = useState<boolean | null>(null)
  const [customEmotion, setCustomEmotion] = useState<string>("")
  const [selectedReportedUsers, setSelectedReportedUsers] = useState<string[]>([])
  const modalRef = useRef<HTMLDivElement>(null)

  const toggleEmotion = (value: string) => {
    setSelectedEmotions((prev) =>
      prev.includes(value) ? prev.filter((e) => e !== value) : [...prev, value]
    )
  }

  // Focus management
  useEffect(() => {
    if (modalRef.current) {
      modalRef.current.focus()
    }
  }, [])

  const emotions = [
    { value: "Enfadado/a", label: "Enfadado/a", emoji: "😡" },
    { value: "contento/a", label: "Contento/a", emoji: "😊" },
    { value: "Triste", label: "Triste", emoji: "😢" },
    { value: "Aburrido/a", label: "Aburrido/a", emoji: "🥱" },
    { value: "asustado/a", label: "Asustado/a", emoji: "😨" },
    { value: "Otra", label: "Otra", emoji: "💭" },
  ]

  const handleSubmit = () => {
    if (isFormValid) {
      const finalEmotions: EmotionRating[] = selectedEmotions.map((value) => ({
        emotion: value === "Otra" ? `Otra: ${customEmotion.trim()}` : value,
        intensity: intensities[value],
      }))
      onSubmit(
        finalEmotions,
        selectedTempted!,
        selectedTempted ? selectedReportedUsers : undefined
      )
    }
  }

  const isFormValid =
    selectedEmotions.length > 0 &&
    selectedEmotions.every((value) => intensities[value] !== undefined) &&
    (!selectedEmotions.includes("Otra") || customEmotion.trim().length > 0) &&
    selectedTempted !== null &&
    (selectedTempted === false || selectedReportedUsers.length > 0 || participants.length === 0)

  return (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 p-2 backdrop-blur-sm sm:px-4 sm:py-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="emotions-checkup-title"
    >
      <div
        ref={modalRef}
        tabIndex={-1}
        className="flex max-h-[calc(100dvh-1rem)] w-full max-w-[500px] flex-col overflow-hidden rounded-2xl border border-border bg-white shadow-2xl focus:outline-none animate-in fade-in zoom-in-95 duration-200 sm:max-h-[calc(100dvh-3rem)]"
      >
        <div className="h-1.5 shrink-0 bg-accent" />
        
        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto overscroll-contain p-4 sm:space-y-6 sm:p-6">
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
              1. ¿Cómo te sientes en este momento? <span className="font-normal text-secondary">(puedes elegir varias)</span>
            </label>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 sm:gap-2.5">
              {emotions.map((emotion) => {
                const isSelected = selectedEmotions.includes(emotion.value)
                return (
                  <button
                    key={emotion.value}
                    type="button"
                    onClick={() => toggleEmotion(emotion.value)}
                    aria-pressed={isSelected}
                    className={`flex flex-col items-center justify-center rounded-xl border p-2.5 text-sm font-medium transition-all sm:p-3 ${
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

            {selectedEmotions.includes("Otra") && (
              <div className="mt-3 space-y-1.5 animate-in fade-in slide-in-from-top-1 duration-150">
                <label className="block text-xs font-semibold text-secondary">
                  Especifica otra emoción:
                </label>
                <textarea
                  value={customEmotion}
                  onChange={(e) => setCustomEmotion(e.target.value)}
                  placeholder="¿Cómo te sientes?"
                  rows={3}
                  className="w-full min-h-24 resize-y px-3 py-2 text-sm leading-relaxed rounded-xl border border-border focus:border-accent focus:ring-1 focus:ring-accent/20 outline-none"
                  maxLength={MAX_CUSTOM_EMOTION_LENGTH}
                />
                <p className="text-right text-xs text-secondary" aria-live="polite">
                  {customEmotion.length}/{MAX_CUSTOM_EMOTION_LENGTH} caracteres
                </p>
              </div>
            )}

            {selectedEmotions.length > 0 && (
              <div className="mt-3 space-y-3 animate-in fade-in slide-in-from-top-1 duration-150">
                {selectedEmotions.map((value) => {
                  const label = emotions.find((e) => e.value === value)?.label ?? value
                  return (
                    <div key={value} className="space-y-1.5">
                      <p className="text-xs font-semibold text-secondary">
                        Intensidad de &quot;{label}&quot;
                      </p>
                      <div className="grid grid-cols-5 gap-1.5">
                        {INTENSITY_SCALE.map((level) => {
                          const isChosen = intensities[value] === level
                          return (
                            <button
                              key={level}
                              type="button"
                              onClick={() => setIntensities((prev) => ({ ...prev, [value]: level }))}
                              aria-pressed={isChosen}
                              className={`py-2 rounded-lg border text-sm font-semibold transition-all ${
                                isChosen
                                  ? "border-accent bg-accent-soft text-accent ring-2 ring-accent/30"
                                  : "border-border text-secondary hover:border-accent-hover hover:bg-bg-feed"
                              }`}
                            >
                              {level}
                            </button>
                          )
                        })}
                      </div>
                      <div className="flex justify-between text-[10px] text-secondary px-0.5">
                        <span>Poco intenso</span>
                        <span>Muy intenso</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          {/* Question 2: Tempted to report? */}
          <div className="space-y-3">
            <label className="block text-sm font-semibold text-primary">
              2. ¿Has tenido la tentación de reportar a algún usuario de la plataforma?
            </label>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 sm:gap-3">
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
          <div className="flex items-start gap-3 rounded-xl border border-border/60 bg-bg-feed p-3 sm:p-4">
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
        <div className="flex shrink-0 justify-end border-t border-border bg-bg-feed px-4 py-3 sm:px-6 sm:py-4">
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
