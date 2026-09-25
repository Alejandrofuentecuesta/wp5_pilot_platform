"use client"

import { useState } from "react"
import type { AgentImpression, FinalReportBlockSurvey } from "@/lib/types"

interface AgentImpressionSurveyProps {
  agentNames: string[]
  blockedAgentNames: string[]
  submitting: boolean
  error: string | null
  onSubmit: (ratings: AgentImpression[], finalReportBlockSurvey: FinalReportBlockSurvey) => void
}

// Shared by the "actually blocked" and "tempted to block/report" branches
// below — the underlying content concerns are the same regardless of which
// action the participant took (or considered taking).
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
    <fieldset className="mt-4 space-y-2">
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

function toggleItem(current: string[], item: string) {
  return current.includes(item)
    ? current.filter((value) => value !== item)
    : [...current, item]
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
    <fieldset className="space-y-2">
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
  const [blockReasons, setBlockReasons] = useState<string[]>([])
  const [blockOther, setBlockOther] = useState("")
  const [temptedNames, setTemptedNames] = useState<string[]>([])
  const [temptedReasons, setTemptedReasons] = useState<string[]>([])
  const [temptedOther, setTemptedOther] = useState("")

  const hasBlocks = blockedAgentNames.length > 0
  const blockOtherComplete = !blockReasons.includes(OTHER_REASON) || blockOther.trim().length > 0
  const blockSectionComplete = !hasBlocks || (blockReasons.length > 0 && blockOtherComplete)

  const temptedOtherComplete = !temptedReasons.includes(OTHER_REASON) || temptedOther.trim().length > 0
  const temptedSectionComplete = temptedNames.length === 0 || (temptedReasons.length > 0 && temptedOtherComplete)

  const complete = blockSectionComplete && temptedSectionComplete

  const submitSelected = () => {
    if (!complete) return
    const tempted = temptedNames.length > 0
    const finalReportBlockSurvey: FinalReportBlockSurvey = {
      reported_message_ids: [],
      reported_examples: [],
      report_reasons: tempted ? temptedReasons : [],
      report_other: temptedReasons.includes(OTHER_REASON) ? temptedOther.trim() || null : null,
      tempted_to_report: tempted,
      tempted_report_agent_names: temptedNames,
      blocked_agent_names: blockedAgentNames,
      block_reasons: hasBlocks ? blockReasons : [],
      block_other: blockReasons.includes(OTHER_REASON) ? blockOther.trim() || null : null,
      tempted_to_block: hasBlocks ? null : tempted,
      tempted_block_agent_names: hasBlocks ? [] : temptedNames,
    }
    onSubmit([], finalReportBlockSurvey)
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
          {hasBlocks && (
            <section className="rounded-2xl border border-border bg-bg-feed px-4 py-4">
              <h2 className="m-0 text-base font-semibold text-primary">Usuarios bloqueados</h2>
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
                onToggle={(reason) => setBlockReasons((current) => toggleItem(current, reason))}
                onOtherChange={setBlockOther}
              />
            </section>
          )}

          <section className="rounded-2xl border border-border bg-bg-feed px-4 py-4">
            <h2 className="m-0 text-base font-semibold text-primary">
              {hasBlocks ? "¿Alguien más?" : "¿A quién te has sentido tentado/a de bloquear o reportar?"}
            </h2>
            <p className="mt-1 text-sm leading-6 text-secondary">
              {hasBlocks
                ? "Además de a quien ya has bloqueado, ¿te has sentido tentado/a de bloquear o reportar a alguien más?"
                : "Selecciona a quién, si aplica. Si no ha sido nadie, deja esto vacío."}
            </p>
            <div className="mt-3">
              <AgentNameChecklist
                title="A quién"
                names={agentNames}
                selected={temptedNames}
                onToggle={(name) => setTemptedNames((current) => toggleItem(current, name))}
              />
            </div>
            {temptedNames.length > 0 && (
              <ReasonChecklist
                title="¿Por qué?"
                reasons={CONTENT_REASONS}
                selectedReasons={temptedReasons}
                otherValue={temptedOther}
                onToggle={(reason) => setTemptedReasons((current) => toggleItem(current, reason))}
                onOtherChange={setTemptedOther}
              />
            )}
          </section>
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
