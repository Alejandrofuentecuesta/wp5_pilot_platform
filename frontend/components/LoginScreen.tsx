"use client"

import { useCallback, useMemo, useState } from "react"

import { getPreChatSurvey } from "@/lib/pre-chat-surveys"
import type { ParticipantStance, SessionIntakeResponse } from "@/lib/types"

interface LoginScreenProps {
  initialUsername: string
  onPreview: (token: string) => Promise<SessionIntakeResponse>
  onStart: (token: string, username: string, stance: ParticipantStance) => Promise<void>
}

type LoginStep = "token" | "instructions" | "stance"

export default function LoginScreen({
  initialUsername,
  onPreview,
  onStart,
}: LoginScreenProps) {
  const [step, setStep] = useState<LoginStep>("instructions")
  const [token, setToken] = useState("")
  const [username, setUsername] = useState(initialUsername)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [intake, setIntake] = useState<SessionIntakeResponse | null>(null)
  const [selectedStance, setSelectedStance] = useState<ParticipantStance | null>(null)

  const survey = useMemo(
    () => (intake ? getPreChatSurvey(intake.topic_template_id) : null),
    [intake],
  )

  const resetIntake = useCallback(() => {
    setIntake(null)
    setSelectedStance(null)
    setStep("token")
  }, [])

  const handlePreview = useCallback(async () => {
    if (!token.trim()) {
      setError("Introduce tu token para continuar.")
      return
    }
    setLoading(true)
    setError("")
    try {
      const response = await onPreview(token.trim())
      setIntake(response)
      setSelectedStance(null)
      setStep("stance")
    } catch {
      setError("Token no válido. Inténtalo de nuevo.")
    } finally {
      setLoading(false)
    }
  }, [token, onPreview])

  const handleStart = useCallback(async () => {
    if (!selectedStance) {
      setError("Elige la columna que se acerque más a tu posición.")
      return
    }
    setLoading(true)
    setError("")
    try {
      await onStart(token.trim(), username.trim(), selectedStance)
    } catch {
      setError("No se ha podido iniciar la sesión. Inténtalo de nuevo.")
      setLoading(false)
    }
  }, [selectedStance, token, username, onStart])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && step === "token") {
      e.preventDefault()
      handlePreview()
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-bg-page px-4 py-8">
      <div className="w-full max-w-4xl overflow-hidden rounded-xl border border-border bg-bg-surface shadow-lg">
        <div className="border-b border-border px-6 pb-4 pt-6">
          <div className="flex items-center gap-4">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-accent-soft">
              <svg
                width="24"
                height="24"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                className="text-accent"
                aria-hidden="true"
              >
                <path
                  d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </div>
            <div>
              <h1 className="m-0 text-2xl font-semibold text-primary">Sala de discusión</h1>
              <p className="mt-1 text-sm text-secondary">Antes de entrar en la conversación</p>
            </div>
          </div>
        </div>

        <div className="px-6 py-6">
          {step === "token" && (
            <div className="space-y-5">
              <div>
                <h2 className="text-3xl font-semibold text-primary">Acceso a la plataforma</h2>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-secondary">
                  Introduce tu token de participante. Después responderás a una pregunta breve antes de ver la noticia.
                </p>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <label htmlFor="username" className="mb-1 block text-xs font-medium text-secondary">
                    Nombre visible (opcional)
                  </label>
                  <input
                    id="username"
                    type="text"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder="p. ej. Alicia"
                    className="w-full rounded-lg border border-border bg-bg-surface px-3 py-2.5 text-sm text-primary transition-colors placeholder:text-tertiary focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent/30"
                  />
                </div>
                <div>
                  <label htmlFor="token" className="mb-1 block text-xs font-medium text-secondary">
                    Token de participante
                  </label>
                  <div className="flex gap-2">
                    <input
                      id="token"
                      type="text"
                      value={token}
                      onChange={(e) => {
                        setToken(e.target.value)
                        resetIntake()
                        if (error) setError("")
                      }}
                      onKeyDown={handleKeyDown}
                      placeholder="p. ej. user0002"
                      className="min-w-0 flex-1 rounded-lg border border-border bg-bg-surface px-3 py-2.5 text-sm text-primary transition-colors placeholder:text-tertiary focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent/30"
                      autoFocus
                    />
                    <button
                      type="button"
                      onClick={handlePreview}
                      disabled={loading}
                      className="rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-50"
                    >
                      {loading ? "Comprobando..." : "Siguiente"}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {step === "instructions" && (
            <div className="space-y-6">
              <div>
                <h2 className="text-4xl font-semibold text-primary">Antes de empezar</h2>
                <p className="mt-2 max-w-3xl text-base font-semibold leading-7 text-secondary">
                  Después introducirás tu token, responderás a una pregunta breve, leerás una noticia y finalmente
                  entrarás al chat.
                </p>
              </div>

              <div className="grid gap-3 md:grid-cols-4">
                {[
                  ["1", "Introducir token"],
                  ["2", "Responder una pregunta"],
                  ["3", "Leer una noticia"],
                  ["4", "Entrar al chat"],
                ].map(([number, label]) => (
                  <div key={number} className="flex items-center gap-3 rounded-xl border border-border bg-bg-feed px-4 py-3">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent text-base font-semibold text-white">
                      {number}
                    </span>
                    <span className="text-sm font-medium text-primary">{label}</span>
                  </div>
                ))}
              </div>

              <div className="rounded-xl border border-border bg-bg-surface p-5">
                <h3 className="text-2xl font-semibold text-primary">Durante la discusión, puedes:</h3>
                <ul className="mt-4 space-y-3 text-base leading-7 text-primary">
                  <li className="flex gap-3 items-start">
                    <span className="mt-2.5 h-2.5 w-2.5 shrink-0 rounded-full bg-accent" />
                    <span>
                      <strong>Escribir mensajes</strong> cuando tengas algo que decir.
                    </span>
                  </li>
                  <li className="flex gap-3 items-start">
                    <span className="mt-2.5 h-2.5 w-2.5 shrink-0 rounded-full bg-accent" />
                    <span className="inline-flex items-center flex-wrap gap-1.5">
                      <strong>Responder a otros</strong>
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs bg-accent-soft text-accent font-medium">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                          <polyline points="9 17 4 12 9 7" />
                          <path d="M20 18v-2a4 4 0 00-4-4H4" />
                        </svg>
                        Reply
                      </span>
                      cuando estés de acuerdo, en desacuerdo o quieras reaccionar a un comentario.
                    </span>
                  </li>
                  <li className="flex gap-3 items-start">
                    <span className="mt-2.5 h-2.5 w-2.5 shrink-0 rounded-full bg-accent" />
                    <span className="inline-flex items-center flex-wrap gap-1.5">
                      <strong>Dar Like</strong>
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs bg-red-50 text-danger font-medium">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                          <path d="M20.84 4.61a5.5 5.5 0 00-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 00-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 000-7.78z" />
                        </svg>
                        Like
                      </span>
                      a los comentarios que apoyes o con los que estés de acuerdo.
                    </span>
                  </li>
                  <li className="flex gap-3 items-start">
                    <span className="mt-2.5 h-2.5 w-2.5 shrink-0 rounded-full bg-accent" />
                    <span className="inline-flex items-center flex-wrap gap-1.5">
                      <strong>Reportar o bloquear</strong>
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs bg-red-50 text-danger font-medium">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                          <path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z" />
                          <line x1="4" y1="22" x2="4" y2="15" />
                        </svg>
                        Report
                      </span>
                      comentarios o usuarios que te parezcan inapropiados, molestos o incómodos.
                    </span>
                  </li>
                  <li className="flex gap-3 items-start">
                    <span className="mt-2.5 h-2.5 w-2.5 shrink-0 rounded-full bg-accent" />
                    <span>
                      <strong>Consultar otras pestañas</strong> si quieres buscar información para participar en el debate.
                    </span>
                  </li>
                  <li className="flex gap-3 items-start">
                    <span className="mt-2.5 h-2.5 w-2.5 shrink-0 rounded-full bg-accent" />
                    <span className="inline-flex items-center flex-wrap gap-1.5">
                      <strong>Salir de la discusión</strong>
                      <span className="px-2 py-0.5 text-xs border border-danger/35 bg-danger/5 text-danger font-medium rounded-lg">
                        Salir
                      </span>
                      si normalmente dejarías de participar.
                    </span>
                  </li>
                </ul>
              </div>

              <p className="max-w-3xl text-base leading-7 text-primary font-medium">
                Tu tarea en esta actividad consiste en formar parte activa de la discusión: comparte tus puntos de vista,
                responde a otros participantes y mantén la conversación viva a lo largo de toda la sesión.
              </p>

              <div className="rounded-xl border-2 border-[#e0a800] bg-[#fff7b8] p-5 text-[#4d3f00]">
                <h3 className="text-2xl font-semibold">Importante</h3>
                <div className="mt-3 space-y-2 text-sm leading-6">
                  <p>El experimento dura aproximadamente 20 minutos y debe hacerse seguido, en una sola sesión.</p>
                  <p>Si no tienes tiempo para completarlo ahora, por favor entra en otro momento.</p>
                  <p>
                    No escribas nombres reales, datos de contacto ni información personal tuya o de otras personas en tus
                    comentarios. Para proteger la privacidad de todos, participa sin incluir datos que puedan identificar
                    a alguien.
                  </p>
                  <p>Si sales después de entrar al chat, no podrás volver a la misma sesión.</p>
                </div>
              </div>

              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={() => setStep("token")}
                  className="rounded-lg bg-accent px-6 py-3 text-sm font-medium text-white transition-colors hover:bg-accent-hover"
                >
                  Siguiente
                </button>
              </div>
            </div>
          )}

          {step === "stance" && survey && (
            <div className="space-y-5">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-secondary">
                  {survey.title}
                </p>
                <h2 className="mt-1 text-2xl font-semibold text-primary">{survey.prompt}</h2>
                <p className="mt-1 text-sm text-secondary">
                  Lee ambas columnas y elige la que en conjunto se acerque más a tu posición. No hace falta que estés
                  completamente de acuerdo con todas las frases.
                </p>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                {survey.columns.map((column) => {
                  const selected = selectedStance === column.id
                  return (
                    <button
                      key={column.id}
                      type="button"
                      onClick={() => setSelectedStance(column.id)}
                      className={`rounded-xl border p-4 text-left transition-colors ${
                        selected
                          ? "border-accent bg-accent/5 ring-1 ring-accent/20"
                          : "border-border bg-bg-surface hover:border-accent/40"
                      }`}
                    >
                      <p className="mb-3 text-sm font-semibold text-primary">{column.label}</p>
                      <ul className="space-y-3 text-sm text-primary">
                        {column.statements.map((statement) => (
                          <li key={statement} className="leading-6">
                            {statement}
                          </li>
                        ))}
                      </ul>
                    </button>
                  )
                })}
              </div>

              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <button
                  type="button"
                  onClick={() => setStep("token")}
                  className="rounded-lg border border-border px-4 py-2.5 text-sm font-medium text-secondary transition-colors hover:border-accent hover:text-primary"
                >
                  Volver
                </button>
                <button
                  type="button"
                  onClick={handleStart}
                  disabled={loading || !selectedStance}
                  className="rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-50"
                >
                  {loading ? "Entrando..." : "Continuar a la noticia"}
                </button>
              </div>
            </div>
          )}

          {error && <p className="mt-5 text-sm text-danger">{error}</p>}
        </div>
      </div>
    </div>
  )
}
