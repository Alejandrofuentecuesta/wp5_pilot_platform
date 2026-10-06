"use client"

import { useState } from "react"
import type { AgentImpression, FinalReportBlockSurvey } from "@/lib/types"

interface AgentImpressionSurveyProps {
  agentNames: string[]
  blockedAgentNames: string[]
  hasReportedDuringChat?: boolean
  reportedMessageIds?: string[]
  isEarlyExit?: boolean
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

export const WHY_NOT_REPORTED_REASONS = [
  "No merecía la pena / No era lo bastante grave",
  "Eran demasiados comentarios molestos para ir reportando",
  "Sentí que no iba a cambiar nada / No sirve de nada reportar",
  "Prefería contestar o rebatir directamente en la conversación",
  "No quería interrumpir el ritmo del debate",
  "No me acordé de la opción de reportar o no supe cómo utilizarla",
  "No vi ningún comentario que considerara necesario reportar",
] as const

export const WHY_NOT_REPORTED_OTHER = "Otros motivos (opción abierta)"

function RatingSlider({
  label,
  description,
  min = 1,
  max = 7,
  value,
  onChange,
  leftLabel,
  midLabel,
  rightLabel,
}: {
  label: string
  description?: string
  min?: number
  max?: number
  value: number | null
  onChange: (val: number) => void
  leftLabel: string
  midLabel?: string
  rightLabel: string
}) {
  const steps = Array.from({ length: max - min + 1 }, (_, i) => min + i)
  return (
    <div className="space-y-2.5">
      <div>
        <p className="text-sm font-semibold text-primary">{label}</p>
        {description && (
          <p className="mt-1 text-xs leading-relaxed text-secondary">{description}</p>
        )}
      </div>
      <div className="rounded-xl border border-border bg-bg-surface p-4 space-y-3">
        <div className="flex items-center justify-between text-xs font-medium text-secondary">
          <span className="max-w-[32%] text-left">1: {leftLabel}</span>
          {midLabel && <span className="max-w-[32%] text-center">4: {midLabel}</span>}
          <span className="max-w-[32%] text-right">7: {rightLabel}</span>
        </div>
        <div className="relative py-2">
          <input
            type="range"
            min={min}
            max={max}
            step={1}
            value={value ?? 4}
            onChange={(e) => onChange(Number(e.target.value))}
            className="w-full h-2.5 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-accent focus:outline-none focus:ring-2 focus:ring-accent/30"
          />
          <div className="flex justify-between px-1 pt-1.5 text-xs text-secondary font-mono select-none">
            {steps.map((num) => (
              <button
                key={num}
                type="button"
                onClick={() => onChange(num)}
                className={`w-7 h-7 flex items-center justify-center rounded-full text-xs font-semibold transition-all ${
                  value === num
                    ? "bg-accent text-white shadow-sm ring-2 ring-accent/30"
                    : "text-secondary hover:bg-gray-100"
                }`}
              >
                {num}
              </button>
            ))}
          </div>
        </div>
        <div className="text-center pt-1">
          {value !== null ? (
            <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-accent-soft text-accent">
              Puntuación seleccionada: {value} / {max}
            </span>
          ) : (
            <span className="text-xs text-amber-800 bg-amber-50 px-2.5 py-1 rounded-md border border-amber-200/60 inline-block font-medium">
              Desliza el control o pulsa un número para seleccionar
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

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
  hasReportedDuringChat = false,
  reportedMessageIds = [],
  isEarlyExit = false,
  submitting,
  error,
  onSubmit,
}: AgentImpressionSurveyProps) {
  // Early exit questions
  const [earlyExitAgreement, setEarlyExitAgreement] = useState<number | null>(null)
  const [earlyExitIncivility, setEarlyExitIncivility] = useState<number | null>(null)
  const [earlyExitIncivilityCategory, setEarlyExitIncivilityCategory] = useState<string | null>(null)
  const [earlyExitHumanAi, setEarlyExitHumanAi] = useState<string | null>(null)
  const [earlyExitComposition, setEarlyExitComposition] = useState<string | null>(null)
  const [earlyExitFearSocialSanctions, setEarlyExitFearSocialSanctions] = useState<number | null>(null)

  // Block questions
  const [blockNames, setBlockNames] = useState<string[]>([])
  const [blockReasons, setBlockReasons] = useState<string[]>([])
  const [blockOther, setBlockOther] = useState("")

  // Report temptation questions
  const [reportNames, setReportNames] = useState<string[]>([])
  const [reportReasons, setReportReasons] = useState<string[]>([])
  const [reportOther, setReportOther] = useState("")

  // Why not reported questions
  const [whyNotReported, setWhyNotReported] = useState<string[]>([])
  const [whyNotReportedOther, setWhyNotReportedOther] = useState("")

  const hasBlocks = blockedAgentNames.length > 0

  const earlyExitComplete =
    !isEarlyExit ||
    (earlyExitAgreement !== null &&
      earlyExitIncivility !== null &&
      earlyExitIncivilityCategory !== null &&
      earlyExitHumanAi !== null &&
      earlyExitComposition !== null &&
      earlyExitFearSocialSanctions !== null)

  const blockOtherComplete = !blockReasons.includes(OTHER_REASON) || blockOther.trim().length > 0
  const blockAnswered = hasBlocks || blockNames.length > 0
  const blockSectionComplete = !blockAnswered || (blockReasons.length > 0 && blockOtherComplete)

  const reportOtherComplete = !reportReasons.includes(OTHER_REASON) || reportOther.trim().length > 0
  const reportSectionComplete =
    reportNames.length === 0 || (reportReasons.length > 0 && reportOtherComplete)

  const whyNotReportedOtherComplete =
    !whyNotReported.includes(WHY_NOT_REPORTED_OTHER) || whyNotReportedOther.trim().length > 0
  const whyNotReportedComplete =
    whyNotReported.length > 0 && whyNotReportedOtherComplete

  const complete =
    earlyExitComplete &&
    blockSectionComplete &&
    reportSectionComplete &&
    whyNotReportedComplete

  const submitSelected = () => {
    if (!complete) return
    const temptedToBlock = blockNames.length > 0
    const temptedToReport = reportNames.length > 0
    const finalReportBlockSurvey: FinalReportBlockSurvey = {
      reported_message_ids: reportedMessageIds,
      reported_examples: [],
      report_reasons: temptedToReport ? reportReasons : [],
      report_other:
        temptedToReport && reportReasons.includes(OTHER_REASON) ? reportOther.trim() || null : null,
      tempted_to_report: temptedToReport,
      tempted_report_agent_names: reportNames,
      blocked_agent_names: blockedAgentNames,
      block_reasons: blockAnswered ? blockReasons : [],
      block_other:
        blockAnswered && blockReasons.includes(OTHER_REASON) ? blockOther.trim() || null : null,
      tempted_to_block: hasBlocks ? null : temptedToBlock,
      tempted_block_agent_names: hasBlocks ? [] : blockNames,
      why_not_reported: whyNotReported,
      why_not_reported_other:
        whyNotReported.includes(WHY_NOT_REPORTED_OTHER)
          ? whyNotReportedOther.trim() || null
          : null,
      early_exit_agreement: isEarlyExit ? earlyExitAgreement : null,
      early_exit_incivility: isEarlyExit ? earlyExitIncivility : null,
      early_exit_incivility_category: isEarlyExit ? earlyExitIncivilityCategory : null,
      early_exit_human_ai: isEarlyExit ? earlyExitHumanAi : null,
      early_exit_composition: isEarlyExit ? earlyExitComposition : null,
      early_exit_fear_social_sanctions: isEarlyExit ? earlyExitFearSocialSanctions : null,
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
            Unas últimas preguntas sobre la conversación
          </h1>
          <p className="mt-2 text-sm leading-6 text-secondary">
            Tus respuestas ayudan a entender qué tipo de comentarios o usuarios se perciben como problemáticos. Ningún otro participante verá esta información.
          </p>
        </div>

        <div className="space-y-6 px-4 py-4 sm:px-6">
          {/* Early Exit Questions (only shown when leaving early via exit modal) */}
          {isEarlyExit && (
            <section className="rounded-2xl border border-amber-200 bg-amber-50/30 p-4 space-y-6 sm:p-5">
              {/* Slider 1: Opinion match / like-mindedness */}
              <RatingSlider
                label="1. Pensando en la conversación que acabas de tener en la sala de discusión, ¿en general, hasta qué punto sentiste que las opiniones expresadas por las otras personas coincidían con las tuyas sobre el tema debatido?"
                min={1}
                max={7}
                value={earlyExitAgreement}
                onChange={setEarlyExitAgreement}
                leftLabel="No coincidían en absoluto"
                midLabel="Coincidían parcialmente"
                rightLabel="Coincidían completamente"
              />

              {/* Incivility definition block */}
              <div className="rounded-xl border border-amber-200/60 bg-amber-50/50 p-3 text-xs leading-relaxed text-secondary">
                <strong className="text-primary font-semibold">Definición de incivilidad: </strong>
                La incivilidad online se entiende como todo intercambio verbal grosero, descortés u ofensivo que denigra opiniones discrepantes. También se incluyen los discursos discriminatorios o de odio contra individuos o grupos a los que se les atribuyen estereotipos negativos por razón de su identidad social, así como los mensajes que amenazan los valores y libertades democráticas.
              </div>

              {/* Question 2 Part 1: Incivility level */}
              <RatingSlider
                label="2. Teniendo en cuenta la definición de incivilidad de más arriba, pensando en la conversación que acabas de tener en la sala de discusión, ¿en general, hasta qué punto sentiste que las opiniones expresadas por las otras personas eran inciviles?"
                min={1}
                max={7}
                value={earlyExitIncivility}
                onChange={setEarlyExitIncivility}
                leftLabel="Poco o nada incivil"
                midLabel="Moderadamente incivil"
                rightLabel="Muy incivil"
              />

              {/* Question 2 Part 2: Incivility category */}
              <fieldset className="space-y-2">
                <legend className="text-sm font-semibold text-primary">
                  ¿Con cuál de estas opciones describirías tu conversación en la sala de discusión?
                </legend>
                <div className="space-y-2 pt-1">
                  {[
                    "(1) Poco incivil, es decir, algún mensaje incivil esporádico",
                    "(2) Moderadamente incivil, aproximadamente la mitad de los mensajes eran inciviles",
                    "(3) Muy incivil, el tono general y la mayoría de los mensajes eran claramente inciviles",
                  ].map((option) => (
                    <label
                      key={option}
                      className={`flex cursor-pointer items-center gap-3 rounded-xl border px-3 py-2.5 text-sm transition-colors ${
                        earlyExitIncivilityCategory === option
                          ? "border-accent bg-accent-soft/50 text-primary font-medium"
                          : "border-border bg-bg-surface text-secondary hover:border-accent"
                      }`}
                    >
                      <input
                        type="radio"
                        name="early-exit-incivility-category"
                        value={option}
                        checked={earlyExitIncivilityCategory === option}
                        onChange={() => setEarlyExitIncivilityCategory(option)}
                        className="h-4 w-4 text-accent focus:ring-accent"
                      />
                      <span>{option}</span>
                    </label>
                  ))}
                </div>
              </fieldset>

              {/* Question 3: Human vs AI */}
              <fieldset className="space-y-2">
                <legend className="text-sm font-semibold text-primary">
                  3. En general, durante la conversación de hoy en la sala de discusión, ¿crees que las otras personas con las que interactuaste eran...?
                </legend>
                <div className="space-y-2 pt-1">
                  {[
                    "Definitivamente humanas",
                    "Probablemente humanas",
                    "No estoy seguro/a",
                    "Probablemente una IA",
                    "Definitivamente una IA",
                  ].map((option) => (
                    <label
                      key={option}
                      className={`flex cursor-pointer items-center gap-3 rounded-xl border px-3 py-2.5 text-sm transition-colors ${
                        earlyExitHumanAi === option
                          ? "border-accent bg-accent-soft/50 text-primary font-medium"
                          : "border-border bg-bg-surface text-secondary hover:border-accent"
                      }`}
                    >
                      <input
                        type="radio"
                        name="early-exit-human-ai"
                        value={option}
                        checked={earlyExitHumanAi === option}
                        onChange={() => setEarlyExitHumanAi(option)}
                        className="h-4 w-4 text-accent focus:ring-accent"
                      />
                      <span>{option}</span>
                    </label>
                  ))}
                </div>
              </fieldset>

              {/* Question 4: Composition */}
              <fieldset className="space-y-2">
                <legend className="text-sm font-semibold text-primary">
                  4. ¿Crees que todas las personas en la conversación eran del mismo tipo (todos humanos o todos IA), o crees que había una mezcla de ambos?
                </legend>
                <div className="space-y-2 pt-1">
                  {[
                    "Todos eran humanos",
                    "Todos eran IA",
                    "Había una mezcla de humanos e IA",
                    "No estoy seguro/a",
                  ].map((option) => (
                    <label
                      key={option}
                      className={`flex cursor-pointer items-center gap-3 rounded-xl border px-3 py-2.5 text-sm transition-colors ${
                        earlyExitComposition === option
                          ? "border-accent bg-accent-soft/50 text-primary font-medium"
                          : "border-border bg-bg-surface text-secondary hover:border-accent"
                      }`}
                    >
                      <input
                        type="radio"
                        name="early-exit-composition"
                        value={option}
                        checked={earlyExitComposition === option}
                        onChange={() => setEarlyExitComposition(option)}
                        className="h-4 w-4 text-accent focus:ring-accent"
                      />
                      <span>{option}</span>
                    </label>
                  ))}
                </div>
              </fieldset>

              {/* Slider 5: Fear of social sanctions */}
              <RatingSlider
                label="5. ¿En algún momento de la sesión sentiste miedo o preocupación a que los demás participantes te juzgasen negativamente o te atacaran por decir lo que pensabas?"
                min={1}
                max={7}
                value={earlyExitFearSocialSanctions}
                onChange={setEarlyExitFearSocialSanctions}
                leftLabel="Ningún miedo o preocupación"
                midLabel="Preocupación moderada"
                rightLabel="Mucho miedo o preocupación"
              />
            </section>
          )}

          {/* Block Section */}
          <section className="rounded-2xl border border-border bg-bg-feed px-4 py-4">
            {hasBlocks ? (
              <>
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
              </>
            ) : (
              <>
                <h2 className="m-0 text-base font-semibold text-primary">
                  ¿Te has sentido tentado/a de bloquear a alguien?
                </h2>
                <p className="mt-1 text-sm leading-6 text-secondary">
                  Selecciona a quién. Si no ha sido nadie, deja esto vacío.
                </p>
                <div className="mt-3">
                  <AgentNameChecklist
                    title="A quién"
                    names={agentNames}
                    selected={blockNames}
                    onToggle={(name) => setBlockNames((current) => toggleItem(current, name))}
                  />
                </div>
              </>
            )}
            {blockAnswered && (
              <ReasonChecklist
                title="¿Por qué?"
                reasons={CONTENT_REASONS}
                selectedReasons={blockReasons}
                otherValue={blockOther}
                onToggle={(reason) => setBlockReasons((current) => toggleItem(current, reason))}
                onOtherChange={setBlockOther}
              />
            )}
          </section>

          {/* Report Section */}
          <section className="rounded-2xl border border-border bg-bg-feed px-4 py-4 space-y-5">
            <div>
              <h2 className="m-0 text-base font-semibold text-primary">
                {hasReportedDuringChat
                  ? "Además de los mensajes que ya reportaste, ¿hubo otros participantes a los que te sentiste tentado/a de reportar pero finalmente decidiste no hacerlo?"
                  : "¿Hubo participantes a los que te sentiste tentado/a de reportar pero finalmente decidiste no hacerlo?"}
              </h2>
              <p className="mt-1 text-sm leading-6 text-secondary">
                {hasReportedDuringChat
                  ? "Selecciona a quién o quiénes pensaste en reportar. Si no hubo nadie más, déjalo vacío."
                  : "Selecciona a quién o quiénes pensaste en reportar. Si no fue nadie, déjalo vacío."}
              </p>
              <div className="mt-3">
                <AgentNameChecklist
                  title="A quién"
                  names={agentNames}
                  selected={reportNames}
                  onToggle={(name) => setReportNames((current) => toggleItem(current, name))}
                />
              </div>
            </div>

            {reportNames.length > 0 && (
              <ReasonChecklist
                title="¿Por qué te sentiste tentado/a a reportar a ese usuario o usuarios?"
                reasons={CONTENT_REASONS}
                selectedReasons={reportReasons}
                otherValue={reportOther}
                onToggle={(reason) => setReportReasons((current) => toggleItem(current, reason))}
                onOtherChange={setReportOther}
              />
            )}

            {/* Why not reported question (for all participants) */}
            <div className="border-t border-border/80 pt-4">
              <fieldset className="space-y-2">
                <legend className="text-sm font-semibold text-primary">
                  En los casos en que decidiste NO reportar (o no reportar más veces), ¿cuáles fueron los motivos principales?
                </legend>
                <p className="text-xs text-secondary">
                  Puedes seleccionar varias opciones.
                </p>
                <div className="space-y-2 pt-1">
                  {[...WHY_NOT_REPORTED_REASONS, WHY_NOT_REPORTED_OTHER].map((reason) => {
                    const checked = whyNotReported.includes(reason)
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
                          onChange={() =>
                            setWhyNotReported((current) => toggleItem(current, reason))
                          }
                          className="mt-0.5 h-4 w-4 rounded border-border text-accent focus:ring-accent"
                        />
                        <span>{reason}</span>
                      </label>
                    )
                  })}
                </div>
                {whyNotReported.includes(WHY_NOT_REPORTED_OTHER) && (
                  <textarea
                    rows={3}
                    maxLength={1000}
                    value={whyNotReportedOther}
                    onChange={(event) => setWhyNotReportedOther(event.target.value)}
                    placeholder="Especifica brevemente otros motivos..."
                    className="w-full resize-y rounded-xl border border-border bg-bg-surface px-3 py-2 text-sm leading-relaxed text-primary outline-none focus:border-accent focus:ring-1 focus:ring-accent/20"
                  />
                )}
              </fieldset>
            </div>
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
              {isEarlyExit && !earlyExitComplete
                ? "Por favor, responde a las preguntas iniciales sobre la conversación antes de finalizar."
                : !whyNotReportedComplete
                ? "Por favor, indica los motivos por los que decidiste no reportar antes de finalizar."
                : "Responde las preguntas sobre bloqueos y reportes antes de finalizar."}
            </p>
          )}
        </div>
      </div>
    </main>
  )
}
