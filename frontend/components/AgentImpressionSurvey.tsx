"use client"

import { useMemo, useState } from "react"
import type { AgentImpression, FinalReportBlockSurvey } from "@/lib/types"

interface AgentImpressionSurveyProps {
  agentNames: string[]
  blockedAgentNames: string[]
  submitting: boolean
  error: string | null
  onSubmit: (ratings: AgentImpression[], finalReportBlockSurvey: FinalReportBlockSurvey) => void
}

const RATING_SCORES = [1, 2, 3, 4, 5] as const
const RATING_LABELS: Record<(typeof RATING_SCORES)[number], string> = {
  1: "Muy mal",
  2: "Mal",
  3: "Neutral",
  4: "Bien",
  5: "Muy bien",
}

// Shared by the block and report sections below — the underlying content
// concerns are the same regardless of which action the participant took
// (or considered taking).
const CONTENT_REASONS = [
  "Porque sus mensajes contenían insultos u ofensas",
  "Porque era hostil o atacaba personalmente a alguien",
  "Porque sus mensajes contenían odio o discriminación hacia un grupo",
  "Porque difundía información falsa",
  "Porque promueve violencia o daño",
  "Porque me resulta molesto o incómodo",
  "Porque no representa bien la posición que quiero defender",
] as const

const OTHER_REASON = "Otros (opción abierta)"

function ReasonChecklist({
  title,
  reasons,
  selectedReasons,
  otherValue,
  onToggle,
  onOtherChange,
}: {
  title: string
  reasons: readonly string[]
  selectedReasons: string[]
  otherValue: string
  onToggle: (reason: string) => void
  onOtherChange: (value: string) => void
}) {
  const otherSelected = selectedReasons.includes(OTHER_REASON)

  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-semibold text-primary">{title}</legend>
      <div className="space-y-2">
        {[...reasons, OTHER_REASON].map((reason) => {
          const checked = selectedReasons.includes(reason)
          return (
            <label
              key={reason}
              className={`flex cursor-pointer items-start gap-3 rounded-xl border px-3 py-2.5 text-sm transition-colors ${
                checked
                  ? "border-accent bg-accent-soft/50 text-primary"
                  : "border-border bg-bg-surface text-secondary hover:border-accent"
              }`}
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={() => onToggle(reason)}
                className="mt-0.5 h-4 w-4 rounded border-border text-accent focus:ring-accent"
              />
              <span>{reason}</span>
            </label>
          )
        })}
      </div>
      {otherSelected && (
        <textarea
          rows={3}
          maxLength={1000}
          value={otherValue}
          onChange={(event) => onOtherChange(event.target.value)}
          placeholder="Especifica brevemente el motivo..."
          className="w-full resize-y rounded-xl border border-border bg-bg-surface px-3 py-2 text-sm leading-relaxed text-primary outline-none focus:border-accent focus:ring-1 focus:ring-accent/20"
        />
      )}
    </fieldset>
  )
}

function toggleReason(current: string[], reason: string) {
  return current.includes(reason)
    ? current.filter((item) => item !== reason)
    : [...current, reason]
}

function AgentNameChecklist({
  title,
  names,
  selected,
  onToggle,
}: {
  title: string
  names: string[]
  selected: string[]
  onToggle: (name: string) => void
}) {
  if (names.length === 0) return null

  return (
    <fieldset className="mt-4 space-y-2">
      <legend className="text-sm font-semibold text-primary">{title}</legend>
      <div className="flex flex-wrap gap-2">
        {names.map((name) => {
          const checked = selected.includes(name)
          return (
            <label
              key={name}
              className={`flex cursor-pointer items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-colors ${
                checked
                  ? "border-accent bg-accent-soft/50 text-primary"
                  : "border-border bg-bg-surface text-secondary hover:border-accent"
              }`}
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={() => onToggle(name)}
                className="h-3.5 w-3.5 rounded border-border text-accent focus:ring-accent"
              />
              {name}
            </label>
          )
        })}
      </div>
    </fieldset>
  )
}

export default function AgentImpressionSurvey({
  agentNames,
  blockedAgentNames,
  submitting,
  error,
  onSubmit,
}: AgentImpressionSurveyProps) {
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [ratings, setRatings] = useState<Record<string, AgentImpression["rating"]>>({})
  const [comments, setComments] = useState<Record<string, string>>({})
  const [blockReasons, setBlockReasons] = useState<string[]>([])
  const [blockOther, setBlockOther] = useState("")
  const [temptedToBlock, setTemptedToBlock] = useState<boolean | null>(null)
  const [temptedBlockNames, setTemptedBlockNames] = useState<string[]>([])
  const [reportReasons, setReportReasons] = useState<string[]>([])
  const [reportOther, setReportOther] = useState("")
  const [temptedToReport, setTemptedToReport] = useState<boolean | null>(null)
  const [temptedReportNames, setTemptedReportNames] = useState<string[]>([])

  const selectedNames = useMemo(
    () => agentNames.filter((name) => selected[name]),
    [agentNames, selected],
  )

  const agentRatingsComplete = selectedNames.every((name) => ratings[name] !== undefined)
  const hasBlocks = blockedAgentNames.length > 0
  const blockOtherComplete = !blockReasons.includes(OTHER_REASON) || blockOther.trim().length > 0
  const blockSectionComplete = hasBlocks
    ? blockReasons.length > 0 && blockOtherComplete
    : temptedToBlock === false || (temptedToBlock === true && blockReasons.length > 0 && blockOtherComplete)
  const reportOtherComplete = !reportReasons.includes(OTHER_REASON) || reportOther.trim().length > 0
  const reportSectionComplete =
    temptedToReport === false ||
    (temptedToReport === true && reportReasons.length > 0 && reportOtherComplete)
  const complete = agentRatingsComplete && blockSectionComplete && reportSectionComplete

  const submitSelected = () => {
    if (!complete) return
    const finalReportBlockSurvey: FinalReportBlockSurvey = {
      reported_message_ids: [],
      reported_examples: [],
      report_reasons: temptedToReport ? reportReasons : [],
      report_other: reportReasons.includes(OTHER_REASON) ? reportOther.trim() || null : null,
      tempted_to_report: temptedToReport,
      tempted_report_agent_names: temptedToReport ? temptedReportNames : [],
      blocked_agent_names: blockedAgentNames,
      block_reasons: hasBlocks || temptedToBlock ? blockReasons : [],
      block_other: blockReasons.includes(OTHER_REASON) ? blockOther.trim() || null : null,
      tempted_to_block: hasBlocks ? null : temptedToBlock,
      tempted_block_agent_names: !hasBlocks && temptedToBlock ? temptedBlockNames : [],
    }
    onSubmit(
      selectedNames.map((name) => ({
        agent_name: name,
        rating: ratings[name],
        comment: (comments[name] || "").trim() || null,
      })),
      finalReportBlockSurvey,
    )
  }

  return (
    <main className="h-dvh overflow-y-auto bg-bg-page px-4 py-6">
      <div className="mx-auto w-full max-w-3xl overflow-hidden rounded-2xl border border-border bg-bg-surface shadow-lg">
        <div className="border-b border-border px-6 py-5">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-accent">
            Antes de terminar
          </p>
          <h1 className="m-0 text-xl font-semibold text-primary">
            Una última pregunta sobre la conversación
          </h1>
          <p className="mt-2 text-sm leading-6 text-secondary">
            Tus respuestas ayudan a entender qué tipo de comentarios o usuarios se perciben como problemáticos. Ningún otro participante verá esta información.
          </p>
        </div>

        <div className="space-y-5 px-4 py-4 sm:px-6">
          <section className="rounded-2xl border border-border bg-bg-feed px-4 py-4">
            <h2 className="m-0 text-base font-semibold text-primary">Usuarios bloqueados</h2>
            {hasBlocks ? (
              <>
                <p className="mt-1 text-sm leading-6 text-secondary">
                  {blockedAgentNames.length > 2
                    ? "Has bloqueado usuarios como estos. ¿Por qué los has bloqueado?"
                    : "Has bloqueado estos usuarios. ¿Por qué los has bloqueado?"}
                </p>
                <div className="my-3 flex flex-wrap gap-2">
                  {blockedAgentNames.slice(0, 2).map((name) => (
                    <span
                      key={name}
                      className="rounded-full border border-border bg-bg-surface px-3 py-1 text-sm font-semibold text-primary"
                    >
                      {name}
                    </span>
                  ))}
                </div>
                <ReasonChecklist
                  title="Selecciona todos los motivos que correspondan."
                  reasons={CONTENT_REASONS}
                  selectedReasons={blockReasons}
                  otherValue={blockOther}
                  onToggle={(reason) => setBlockReasons((current) => toggleReason(current, reason))}
                  onOtherChange={setBlockOther}
                />
              </>
            ) : (
              <>
                <p className="mt-1 text-sm leading-6 text-secondary">
                  No has bloqueado ningún usuario. ¿Te has sentido tentado/a de bloquear a alguien?
                </p>
                <div className="mt-3 flex gap-2">
                  {[{ label: "Sí", value: true }, { label: "No", value: false }].map((option) => (
                    <button
                      key={option.label}
                      type="button"
                      onClick={() => setTemptedToBlock(option.value)}
                      className={`rounded-lg border px-4 py-2 text-sm font-semibold transition-colors ${
                        temptedToBlock === option.value
                          ? "border-accent bg-accent text-white"
                          : "border-border bg-bg-surface text-primary hover:border-accent"
                      }`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
                {temptedToBlock && (
                  <div className="mt-4">
                    <ReasonChecklist
                      title="¿Por qué te has sentido tentado/a?"
                      reasons={CONTENT_REASONS}
                      selectedReasons={blockReasons}
                      otherValue={blockOther}
                      onToggle={(reason) => setBlockReasons((current) => toggleReason(current, reason))}
                      onOtherChange={setBlockOther}
                    />
                    <AgentNameChecklist
                      title="¿A quién?"
                      names={agentNames}
                      selected={temptedBlockNames}
                      onToggle={(name) => setTemptedBlockNames((current) => toggleReason(current, name))}
                    />
                  </div>
                )}
              </>
            )}
          </section>

          <section className="rounded-2xl border border-border bg-bg-feed px-4 py-4">
            <h2 className="m-0 text-base font-semibold text-primary">Mensajes reportados</h2>
            <p className="mt-1 text-sm leading-6 text-secondary">
              ¿Te has sentido tentado/a de reportar algún mensaje?
            </p>
            <div className="mt-3 flex gap-2">
              {[{ label: "Sí", value: true }, { label: "No", value: false }].map((option) => (
                <button
                  key={option.label}
                  type="button"
                  onClick={() => setTemptedToReport(option.value)}
                  className={`rounded-lg border px-4 py-2 text-sm font-semibold transition-colors ${
                    temptedToReport === option.value
                      ? "border-accent bg-accent text-white"
                      : "border-border bg-bg-surface text-primary hover:border-accent"
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>
            {temptedToReport && (
              <div className="mt-4">
                <ReasonChecklist
                  title="¿Por qué te has sentido tentado/a?"
                  reasons={CONTENT_REASONS}
                  selectedReasons={reportReasons}
                  otherValue={reportOther}
                  onToggle={(reason) => setReportReasons((current) => toggleReason(current, reason))}
                  onOtherChange={setReportOther}
                />
                <AgentNameChecklist
                  title="¿A quién?"
                  names={agentNames}
                  selected={temptedReportNames}
                  onToggle={(name) => setTemptedReportNames((current) => toggleReason(current, name))}
                />
              </div>
            )}
          </section>

          {agentNames.length > 0 && (
            <section className="rounded-2xl border border-border bg-bg-feed px-4 py-4">
              <h2 className="m-0 text-base font-semibold text-primary">Valoración opcional de usuarios</h2>
              <p className="mt-1 text-sm leading-6 text-secondary">
                Si quieres, selecciona uno o varios usuarios, puntúalos del 1 (muy mal) al 5 (muy bien) y explica brevemente el motivo.
              </p>
              <div className="mt-3 space-y-3">
                {agentNames.map((name) => {
                  const isSelected = Boolean(selected[name])
                  return (
                    <section
                      key={name}
                      className={`rounded-xl border px-4 py-3 transition-colors ${
                        isSelected
                          ? "border-accent bg-accent-soft/40"
                          : "border-border bg-bg-surface"
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
                              placeholder="Puedes explicar brevemente el motivo..."
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
            </section>
          )}
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
            onClick={submitSelected}
            className="w-full rounded-lg bg-accent px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? "Guardando..." : "Guardar y finalizar"}
          </button>
          {!complete && (
            <p className="mt-2 text-center text-xs text-tertiary">
              Responde las preguntas sobre bloqueos y reportes antes de finalizar.
            </p>
          )}
        </div>
      </div>
    </main>
  )
}
