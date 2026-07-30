"use client"

import { useMemo, useState } from "react"
import type { AgentImpression } from "@/lib/types"

interface AgentImpressionSurveyProps {
  agentNames: string[]
  submitting: boolean
  error: string | null
  onSubmit: (ratings: AgentImpression[]) => void
}

const RATING_SCORES = [1, 2, 3, 4, 5] as const
const RATING_LABELS: Record<(typeof RATING_SCORES)[number], string> = {
  1: "Muy mal",
  2: "Mal",
  3: "Neutral",
  4: "Bien",
  5: "Muy bien",
}

export default function AgentImpressionSurvey({
  agentNames,
  submitting,
  error,
  onSubmit,
}: AgentImpressionSurveyProps) {
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [ratings, setRatings] = useState<Record<string, AgentImpression["rating"]>>({})
  const [comments, setComments] = useState<Record<string, string>>({})

  const selectedNames = useMemo(
    () => agentNames.filter((name) => selected[name]),
    [agentNames, selected],
  )
  const complete =
    selectedNames.length > 0 &&
    selectedNames.every((name) => ratings[name] !== undefined)

  const submitSelected = () => {
    if (!complete) return
    onSubmit(
      selectedNames.map((name) => ({
        agent_name: name,
        rating: ratings[name],
        comment: (comments[name] || "").trim() || null,
      })),
    )
  }

  return (
    <main className="h-dvh overflow-y-auto bg-bg-page px-4 py-6">
      <div className="mx-auto w-full max-w-2xl overflow-hidden rounded-2xl border border-border bg-bg-surface shadow-lg">
        <div className="border-b border-border px-6 py-5">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-accent">
            Antes de terminar
          </p>
          <h1 className="m-0 text-xl font-semibold text-primary">
            ¿Algún usuario te ha caído especialmente bien o mal?
          </h1>
          <p className="mt-2 text-sm leading-6 text-secondary">
            Si quieres, selecciona uno o varios usuarios, puntúalos del 1 (muy
            mal) al 5 (muy bien) y explica brevemente el motivo. Solo aparecen
            usuarios que han escrito durante la sesión. Tu respuesta es anónima
            y ningún otro participante sabrá qué opinión has dado.
          </p>
        </div>

        <div className="space-y-3 px-4 py-4 sm:px-6">
          {agentNames.map((name) => {
            const isSelected = Boolean(selected[name])
            return (
              <section
                key={name}
                className={`rounded-xl border px-4 py-3 transition-colors ${
                  isSelected
                    ? "border-accent bg-accent-soft/40"
                    : "border-border bg-bg-feed"
                }`}
              >
                <label className="flex cursor-pointer items-center gap-3 text-sm font-semibold text-primary">
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() =>
                      setSelected((current) => ({
                        ...current,
                        [name]: !current[name],
                      }))
                    }
                    className="h-4 w-4 rounded border-border text-accent focus:ring-accent"
                  />
                  <span>{name}</span>
                </label>

                {isSelected && (
                  <div className="mt-4 space-y-3">
                    <fieldset>
                      <legend className="mb-2 text-xs font-semibold text-secondary">
                        ¿Qué impresión te ha causado?
                      </legend>
                      <div className="grid grid-cols-5 gap-1.5">
                        {RATING_SCORES.map((score) => {
                          const scoreSelected = ratings[name] === score
                          return (
                            <button
                              key={score}
                              type="button"
                              aria-label={`${name}: ${RATING_LABELS[score]}`}
                              aria-pressed={scoreSelected}
                              onClick={() =>
                                setRatings((current) => ({
                                  ...current,
                                  [name]: score,
                                }))
                              }
                              className={`rounded-lg border px-1 py-2 text-center transition-colors ${
                                scoreSelected
                                  ? "border-accent bg-accent text-white"
                                  : "border-border bg-bg-surface text-primary hover:border-accent"
                              }`}
                            >
                              <span className="block text-sm font-semibold">{score}</span>
                              <span className="hidden text-[10px] sm:block">
                                {RATING_LABELS[score]}
                              </span>
                            </button>
                          )
                        })}
                      </div>
                    </fieldset>

                    <div>
                      <label
                        htmlFor={`agent-comment-${name}`}
                        className="mb-1.5 block text-xs font-semibold text-secondary"
                      >
                        ¿Por qué? (opcional)
                      </label>
                      <textarea
                        id={`agent-comment-${name}`}
                        rows={3}
                        maxLength={1000}
                        value={comments[name] || ""}
                        onChange={(event) =>
                          setComments((current) => ({
                            ...current,
                            [name]: event.target.value,
                          }))
                        }
                        placeholder="Puedes explicar brevemente el motivo…"
                        className="w-full resize-y rounded-xl border border-border bg-bg-surface px-3 py-2 text-sm leading-relaxed text-primary outline-none focus:border-accent focus:ring-1 focus:ring-accent/20"
                      />
                      <p className="mt-1 text-right text-[11px] text-tertiary">
                        {(comments[name] || "").length}/1000
                      </p>
                    </div>
                  </div>
                )}
              </section>
            )
          })}
        </div>

        <div className="border-t border-border px-6 py-4">
          {error && (
            <p className="mb-3 text-sm text-danger" role="alert">
              {error}
            </p>
          )}
          {selectedNames.length > 0 ? (
            <>
              <button
                type="button"
                disabled={!complete || submitting}
                onClick={submitSelected}
                className="w-full rounded-lg bg-accent px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
              >
                {submitting ? "Guardando…" : "Guardar y finalizar"}
              </button>
              {!complete && (
                <p className="mt-2 text-center text-xs text-tertiary">
                  Asigna una puntuación a cada usuario seleccionado.
                </p>
              )}
            </>
          ) : (
            <button
              type="button"
              disabled={submitting}
              onClick={() => onSubmit([])}
              className="w-full rounded-lg border border-border bg-bg-surface px-4 py-3 text-sm font-semibold text-primary transition-colors hover:border-accent disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? "Guardando…" : "Continuar sin valorar a nadie"}
            </button>
          )}
        </div>
      </div>
    </main>
  )
}
