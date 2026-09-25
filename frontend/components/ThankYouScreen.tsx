"use client"

import { useEffect } from "react"
import DebriefingNotice from "./DebriefingNotice"

interface ThankYouScreenProps {
  redirectUrl: string | null
  reason?: string | null
}

// Reasons where the session ended before the participant reached the
// external survey's own debriefing page: the platform cut it short
// (a researcher closing it from the Safety tab), or the participant chose
// to leave early via the exit button. These pause on a manual "continuar"
// instead of auto-redirecting after 2s, and show the deception debriefing
// directly — see SafetyInterventionScreen for participant_safety, which
// gets the same content on its own crisis-first layout.
//
// Note: the backend's real reason for a researcher-initiated close is
// "safety_stop", but chatroom.py deliberately relabels it "closed_by_researcher"
// for the browser (end_for_safety() passes client_reason=), so that's the
// string that actually arrives here — see _publish_session_end.
const EARLY_END_REASONS = new Set(["closed_by_researcher", "user_exit"])

export default function ThankYouScreen({ redirectUrl, reason }: ThankYouScreenProps) {
  const isEarlyEnd = !!reason && EARLY_END_REASONS.has(reason)

  useEffect(() => {
    if (redirectUrl && !isEarlyEnd) {
      const timer = setTimeout(() => {
        window.location.href = redirectUrl
      }, 2000)
      return () => clearTimeout(timer)
    }
  }, [redirectUrl, isEarlyEnd])

  const leaveExperiment = () => {
    if (redirectUrl) window.location.href = redirectUrl
  }

  return (
    <div className="flex items-center justify-center min-h-dvh bg-bg-page px-4 py-6 overflow-y-auto">
      <div className="bg-bg-surface rounded-xl shadow-lg w-full max-w-sm mx-4 overflow-hidden border border-border">
        <div className="px-6 py-8 text-center">
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
                d="M20 6L9 17l-5-5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>
          <h1 className="text-xl font-semibold text-primary m-0">
            ¡Gracias por participar!
          </h1>
          <p className="text-sm text-secondary mt-3">
            {isEarlyEnd
              ? "La sesión se ha cerrado antes de tiempo. Tus aportaciones han quedado registradas."
              : "La discusión ha terminado. Tus aportaciones han quedado registradas."}
          </p>

          {isEarlyEnd ? (
            <>
              <div className="mt-6 border-t border-border pt-5">
                <DebriefingNotice />
              </div>
              {redirectUrl && (
                <button
                  type="button"
                  onClick={leaveExperiment}
                  className="mt-6 w-full rounded-lg bg-accent px-5 py-3 text-sm font-semibold text-white transition-opacity hover:opacity-90"
                >
                  Continuar
                </button>
              )}
            </>
          ) : (
            redirectUrl && (
              <p className="text-xs text-tertiary mt-4">
                Te redirigimos en unos segundos...
              </p>
            )
          )}
        </div>
      </div>
    </div>
  )
}
