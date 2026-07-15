"use client"

import { useEffect, useState } from "react"

import type { ParticipantStance, SessionIntakeResponse } from "@/lib/types"

interface HandoffScreenProps {
  token: string
  stance: ParticipantStance | null
  onPreview: (token: string) => Promise<SessionIntakeResponse>
  onStart: (token: string, username: string, stance: ParticipantStance) => Promise<void>
}

type HandoffStatus = "checking" | "ready" | "invalid"

const ACTIONS = [
  ["Escribir mensajes", "cuando tengas algo que decir."],
  ["Responder a otros", "cuando estés de acuerdo, en desacuerdo o quieras reaccionar a un comentario."],
  ["Dar Like", "a los comentarios que apoyes o con los que estés de acuerdo."],
  ["Reportar o bloquear", "comentarios o usuarios que te parezcan inapropiados, molestos o incómodos."],
  ["Consultar otras pestañas", "si quieres buscar información para participar en el debate."],
  ["Salir de la discusión", "si normalmente dejarías de participar."],
]

export default function HandoffScreen({
  token,
  stance,
  onPreview,
  onStart,
}: HandoffScreenProps) {
  const [status, setStatus] = useState<HandoffStatus>("checking")
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    let cancelled = false
    if (!stance) {
      setStatus("invalid")
      return
    }
    onPreview(token)
      .then(() => {
        if (!cancelled) setStatus("ready")
      })
      .catch(() => {
        if (!cancelled) setStatus("invalid")
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, stance])

  const handleEnter = async () => {
    if (starting || !stance) return
    setStarting(true)
    setError("")
    try {
      await onStart(token, "", stance)
    } catch {
      setError("No se ha podido iniciar la sesión. Inténtalo de nuevo.")
      setStarting(false)
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
          {status === "checking" && (
            <p className="py-10 text-center text-sm text-secondary">Comprobando tu acceso...</p>
          )}

          {status === "invalid" && (
            <div className="space-y-4 py-6 text-center">
              <h2 className="text-2xl font-semibold text-primary">Enlace no válido</h2>
              <p className="mx-auto max-w-xl text-sm leading-6 text-secondary">
                Este enlace de acceso no es válido o ya ha sido utilizado. Por favor, vuelve a la
                página del panel e inténtalo de nuevo desde allí.
              </p>
            </div>
          )}

          {status === "ready" && (
            <div className="space-y-6">
              <div>
                <h2 className="text-4xl font-semibold text-primary">Antes de empezar</h2>
                <p className="mt-2 max-w-3xl text-base font-semibold leading-7 text-secondary">
                  A continuación leerás una noticia y después entrarás al chat.
                </p>
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                {[
                  ["1", "Leer una noticia"],
                  ["2", "Entrar al chat"],
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
                  {ACTIONS.map(([title, text]) => (
                    <li key={title} className="flex gap-3">
                      <span className="mt-2 h-2.5 w-2.5 shrink-0 rounded-full bg-accent" />
                      <span>
                        <strong>{title}</strong> {text}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>

              <p className="max-w-3xl text-base leading-7 text-primary">
                Participa como lo harías normalmente en una conversación online. Si te sientes cómodo/a, te animamos a
                participar activamente durante el chat.
              </p>

              <div className="rounded-xl border-2 border-[#e0a800] bg-[#fff7b8] p-5 text-[#4d3f00]">
                <h3 className="text-2xl font-semibold">Importante</h3>
                <div className="mt-3 space-y-2 text-sm leading-6">
                  <p>El experimento dura aproximadamente 20 minutos y debe hacerse seguido, en una sola sesión.</p>
                  <p>Si no tienes tiempo para completarlo ahora, por favor entra en otro momento.</p>
                  <p>
                    No dejes la plataforma abierta en segundo plano mientras haces otra cosa. Podemos monitorizar el uso
                    pasivo, como dejar la pestaña inactiva o no seguir la discusión.
                  </p>
                  <p>
                    No escribas nombres reales, datos de contacto ni información personal tuya o de otras personas en tus
                    comentarios. Para proteger la privacidad de todos, participa sin incluir datos que puedan identificar
                    a alguien.
                  </p>
                  <p>Si sales después de entrar al chat, no podrás volver a la misma sesión.</p>
                </div>
              </div>

              {error && <p className="text-sm font-medium text-red-600">{error}</p>}

              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={handleEnter}
                  disabled={starting}
                  className="rounded-lg bg-accent px-6 py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-50"
                >
                  {starting ? "Entrando..." : "Siguiente"}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
