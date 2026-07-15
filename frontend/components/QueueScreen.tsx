"use client"

import { useEffect, useRef } from "react"

interface QueueScreenProps {
  position: number
  waitMinutes: number
  slotAvailable: boolean
  onPoll: () => void
  onClaim: () => void
  onExpired: () => void
}

export default function QueueScreen({
  position,
  waitMinutes,
  slotAvailable,
  onPoll,
  onClaim,
  onExpired,
}: QueueScreenProps) {
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const claimingRef = useRef(false)

  useEffect(() => {
    intervalRef.current = setInterval(() => {
      onPoll()
    }, 30_000)
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [onPoll])

  const handleClaim = async () => {
    if (claimingRef.current) return
    claimingRef.current = true
    try {
      await onClaim()
    } finally {
      claimingRef.current = false
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-bg-page px-4 py-8">
      <div className="w-full max-w-lg overflow-hidden rounded-xl border border-border bg-bg-surface shadow-lg">
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
                <circle cx="12" cy="12" r="10" />
                <polyline points="12 6 12 12 16 14" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <div>
              <h1 className="m-0 text-2xl font-semibold text-primary">Sala de discusión</h1>
              <p className="mt-1 text-sm text-secondary">Esperando turno</p>
            </div>
          </div>
        </div>

        <div className="px-6 py-8 text-center">
          {slotAvailable ? (
            <div className="space-y-6">
              <div>
                <p className="text-lg font-medium text-primary">
                  ¡Tu turno ha llegado!
                </p>
                <p className="mt-2 text-sm text-secondary">
                  Pulsa el botón para entrar en la sala de discusión.
                </p>
              </div>
              <button
                onClick={handleClaim}
                className="rounded-lg bg-accent px-8 py-3 text-base font-semibold text-white shadow-md transition-colors hover:bg-accent-hover focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2"
              >
                Entrar en la sala
              </button>
            </div>
          ) : (
            <div className="space-y-6">
              <div>
                <p className="text-sm text-secondary">Tu posición en la cola</p>
                <p className="mt-1 text-5xl font-bold text-primary">{position}</p>
              </div>
              <div>
                <p className="text-sm text-secondary">Tiempo estimado de espera</p>
                <p className="mt-1 text-lg font-medium text-primary">
                  &lt; {waitMinutes} {waitMinutes === 1 ? "minuto" : "minutos"}
                </p>
              </div>
              <div className="flex items-center justify-center gap-2 text-sm text-secondary">
                <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-accent" />
                Actualizando automáticamente
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
