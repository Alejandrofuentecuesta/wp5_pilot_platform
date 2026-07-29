"use client"

import { useMemo, useState } from "react"
import type { AgentRatingValue } from "@/lib/types"

interface AgentRatingSurveyProps {
  agentNames: string[]
  submitting: boolean
  error: string | null
  onSubmit: (ratings: Record<string, AgentRatingValue>) => void
}

const RATING_LABELS: Record<number, string> = {
  1: "Muy mal",
  2: "Mal",
  3: "Neutral",
  4: "Bien",
  5: "Muy bien",
}

const RATING_SCORES = [1, 2, 3, 4, 5] as const

export default function AgentRatingSurvey({
  agentNames,
  submitting,
  error,
  onSubmit,
}: AgentRatingSurveyProps) {
  const [ratings, setRatings] = useState<Record<string, AgentRatingValue>>({})
  const complete = useMemo(
    () => agentNames.every((name) => ratings[name] !== undefined),
    [agentNames, ratings],
  )

  return (
    <main className="h-dvh overflow-y-auto bg-bg-page px-4 py-6">
      <div className="mx-auto w-full max-w-2xl overflow-hidden rounded-2xl border border-border bg-bg-surface shadow-lg">
        <div className="border-b border-border px-6 py-5">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-accent">
            Antes de terminar
          </p>
          <h1 className="m-0 text-xl font-semibold text-primary">
            ¿Qué impresión te ha causado cada usuario?
          </h1>
          <p className="mt-2 text-sm text-secondary">
            Puntúa a cada uno del 1 (muy mal) al 5 (muy bien). No hay respuestas
            correctas o incorrectas.
          </p>
        </div>

        <div className="space-y-3 px-4 py-4 sm:px-6">
          {agentNames.map((name) => (
            <fieldset
              key={name}
              className="rounded-xl border border-border bg-bg-feed px-4 py-3"
            >
              <legend className="px-1 text-sm font-semibold text-primary">
                {name}
              </legend>
              <div className="mt-1 grid grid-cols-5 gap-1.5">
                {RATING_SCORES.map((score) => {
                  const selected = ratings[name] === score
                  return (
                    <button
                      key={score}
                      type="button"
                      aria-label={`${name}: ${RATING_LABELS[score]}`}
                      aria-pressed={selected}
                      onClick={() =>
                        setRatings((current) => ({ ...current, [name]: score }))
                      }
                      className={`rounded-lg border px-1 py-2 text-center transition-colors ${
                        selected
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
              <button
                type="button"
                aria-label={`${name}: Sin opinión en especial`}
                aria-pressed={ratings[name] === "no_opinion"}
                onClick={() =>
                  setRatings((current) => ({
                    ...current,
                    [name]: "no_opinion",
                  }))
                }
                className={`mt-2 w-full rounded-lg border px-3 py-2 text-xs font-medium transition-colors ${
                  ratings[name] === "no_opinion"
                    ? "border-accent bg-accent-soft text-accent"
                    : "border-border bg-bg-surface text-secondary hover:border-accent"
                }`}
              >
                Sin opinión en especial
              </button>
            </fieldset>
          ))}
        </div>

        <div className="border-t border-border px-6 py-4">
          {error && (
            <p className="mb-3 text-sm text-danger" role="alert">
              {error}
            </p>
          )}
          <button
            type="button"
            disabled={!complete || submitting}
            onClick={() => onSubmit(ratings)}
            className="w-full rounded-lg bg-accent px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? "Guardando…" : "Guardar y finalizar"}
          </button>
          {!complete && (
            <p className="mt-2 text-center text-xs text-tertiary">
              Valora a todos los usuarios para continuar.
            </p>
          )}
        </div>
      </div>
    </main>
  )
}
