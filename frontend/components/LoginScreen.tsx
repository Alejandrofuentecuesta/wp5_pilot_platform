"use client"

import { useCallback, useMemo, useState } from "react"

import { getPreChatSurvey } from "@/lib/pre-chat-surveys"
import type { ParticipantStance, SessionIntakeResponse } from "@/lib/types"

interface LoginScreenProps {
  initialUsername: string
  onPreview: (token: string) => Promise<SessionIntakeResponse>
  onStart: (token: string, username: string, stance: ParticipantStance) => Promise<void>
}

export default function LoginScreen({
  initialUsername,
  onPreview,
  onStart,
}: LoginScreenProps) {
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

  const handlePreview = useCallback(async () => {
    if (!token.trim()) {
      setError("Please enter a token")
      return
    }
    setLoading(true)
    setError("")
    try {
      const response = await onPreview(token.trim())
      setIntake(response)
      setSelectedStance(null)
    } catch {
      setError("Invalid token. Please try again.")
    } finally {
      setLoading(false)
    }
  }, [token, onPreview])

  const handleStart = useCallback(async () => {
    if (!selectedStance) {
      setError("Please choose the column closer to your view.")
      return
    }
    setLoading(true)
    setError("")
    try {
      await onStart(token.trim(), username.trim(), selectedStance)
    } catch {
      setError("Could not start the session. Please try again.")
      setLoading(false)
    }
  }, [selectedStance, token, username, onStart])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !intake) {
      e.preventDefault()
      handlePreview()
    }
  }

  return (
    <div className="flex items-center justify-center min-h-dvh bg-bg-page px-4 py-8">
      <div className="bg-bg-surface rounded-xl shadow-lg w-full max-w-4xl overflow-hidden border border-border">
        <div className="px-6 pt-6 pb-4 text-center border-b border-border">
          <div className="w-12 h-12 rounded-xl bg-accent-soft mx-auto mb-3 flex items-center justify-center">
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
          <h1 className="text-xl font-semibold text-primary m-0">Discussion Room</h1>
          <p className="text-sm text-secondary mt-1">
            Enter your token, choose the column closer to your view, and then join a live discussion.
          </p>
        </div>

        <div className="px-6 py-6 space-y-5">
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label htmlFor="username" className="block text-xs font-medium text-secondary mb-1">
                Display name (optional)
              </label>
              <input
                id="username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="e.g. Alice"
                className="w-full px-3 py-2.5 border border-border rounded-lg text-sm text-primary focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/30 transition-colors placeholder:text-tertiary bg-bg-surface"
              />
            </div>
            <div>
              <label htmlFor="token" className="block text-xs font-medium text-secondary mb-1">
                Participant token
              </label>
              <div className="flex gap-2">
                <input
                  id="token"
                  type="text"
                  value={token}
                  onChange={(e) => {
                    setToken(e.target.value)
                    setIntake(null)
                    setSelectedStance(null)
                    if (error) setError("")
                  }}
                  onKeyDown={handleKeyDown}
                  placeholder="e.g. user0002"
                  className="flex-1 px-3 py-2.5 border border-border rounded-lg text-sm text-primary focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/30 transition-colors placeholder:text-tertiary bg-bg-surface"
                  autoFocus
                />
                <button
                  onClick={handlePreview}
                  disabled={loading}
                  className="px-4 py-2.5 bg-accent hover:bg-accent-hover text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
                >
                  {loading && !intake ? "Checking..." : "Continue"}
                </button>
              </div>
            </div>
          </div>

          {survey && (
            <div className="space-y-4 rounded-xl border border-border bg-bg-feed/50 p-4">
              <div className="rounded-xl border border-accent/20 bg-bg-surface p-4 space-y-3">
                <div>
                  <p className="text-[11px] uppercase tracking-[0.18em] text-secondary font-semibold">
                    Antes de entrar
                  </p>
                  <h2 className="text-lg font-semibold text-primary mt-1">
                    Participa como lo harías en una conversación online real
                  </h2>
                </div>
                <p className="text-sm text-primary leading-6">
                  Primero verás una noticia que servirá como punto de partida,
                  pero la actividad no consiste solo en comentar la noticia.
                  Entrarás en una sala de discusión y podrás reaccionar a lo que
                  digan otras personas durante la conversación.
                </p>
                <ul className="grid gap-2 text-sm text-primary leading-6 md:grid-cols-2">
                  <li>Escribe mensajes cuando tengas algo que decir.</li>
                  <li>Responde directamente a quienes estés de acuerdo o en desacuerdo.</li>
                  <li>Da Like a los mensajes que apoyes o compartas.</li>
                  <li>Reporta o bloquea mensajes/usuarios si te parecen inapropiados o molestos.</li>
                  <li>Busca información fuera de la plataforma si normalmente lo harías.</li>
                  <li>Sal de la conversación si normalmente dejarías de participar.</li>
                </ul>
                <p className="text-xs text-secondary leading-5">
                  No hay respuestas correctas o incorrectas. Nos interesa tu
                  reacción natural durante la discusión.
                </p>
              </div>

              <div>
                <p className="text-[11px] uppercase tracking-[0.18em] text-secondary font-semibold">
                  {survey.title}
                </p>
                <h2 className="text-lg font-semibold text-primary mt-1">{survey.prompt}</h2>
                <p className="text-sm text-secondary mt-1">{survey.subtitle}</p>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                {survey.columns.map((column) => {
                  const selected = selectedStance === column.id
                  return (
                    <button
                      key={column.id}
                      type="button"
                      onClick={() => setSelectedStance(column.id)}
                      className={`text-left rounded-xl border p-4 transition-colors ${
                        selected
                          ? "border-accent bg-accent/5 ring-1 ring-accent/20"
                          : "border-border bg-bg-surface hover:border-accent/40"
                      }`}
                    >
                      <p className="text-sm font-semibold text-primary mb-3">{column.label}</p>
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
                <p className="text-xs text-secondary">
                  Choose the column that is overall closer to your view. You do not need to fully agree with every line.
                </p>
                <button
                  onClick={handleStart}
                  disabled={loading || !selectedStance}
                  className="px-4 py-2.5 bg-accent hover:bg-accent-hover text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
                >
                  {loading ? "Joining..." : "Join discussion"}
                </button>
              </div>
            </div>
          )}

          {error && <p className="text-sm text-danger">{error}</p>}
        </div>
      </div>
    </div>
  )
}
