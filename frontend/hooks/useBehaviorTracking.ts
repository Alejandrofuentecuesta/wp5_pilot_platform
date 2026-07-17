import { useCallback, useEffect, useRef, useState } from "react"
import { sendTelemetry } from "@/lib/api"

// Coarse behavioural signals collected client-side for researchers:
// tab visibility, window focus, typing effort, periodic mouse/keyboard
// activity. No keystroke content and no mouse coordinates are captured.

export type TelemetryKind =
  | "tab_hidden"
  | "tab_visible"
  | "window_focus"
  | "window_blur"
  | "compose"
  | "activity"
  | "idle_prompt_shown"
  | "page_unload"

interface QueuedEvent {
  kind: TelemetryKind
  at: string
  data?: Record<string, unknown>
}

interface Options {
  sessionId: string | null
  // Emit coarse behavioural telemetry (tab/focus/typing/mouse).
  trackingEnabled: boolean
  // Show the "please write in the chat" reminder after inactivity.
  idleEnabled: boolean
  idleSeconds: number
}

const HEARTBEAT_MS = 15_000
const FLUSH_MS = 10_000
const IDLE_CHECK_MS = 5_000

export function useBehaviorTracking({
  sessionId,
  trackingEnabled,
  idleEnabled,
  idleSeconds,
}: Options) {
  const [idlePromptVisible, setIdlePromptVisible] = useState(false)

  const queueRef = useRef<QueuedEvent[]>([])
  // The idle reminder is driven purely by whether the participant POSTS
  // messages — reading, typing, mouse movement and tab switches do NOT reset
  // it. This nudges lurkers who are present but not contributing.
  const lastMessageRef = useRef<number>(Date.now())
  const hadMouseRef = useRef(false)
  const hadKeyboardRef = useRef(false)

  // Enqueue an event; only kept if the relevant feature is enabled.
  const enqueue = useCallback(
    (kind: TelemetryKind, data?: Record<string, unknown>) => {
      if (!sessionId) return
      const isIdleEvent = kind === "idle_prompt_shown"
      if (!trackingEnabled && !(isIdleEvent && idleEnabled)) return
      queueRef.current.push({ kind, at: new Date().toISOString(), data })
    },
    [sessionId, trackingEnabled, idleEnabled],
  )

  // Public: record a finished message composition (called on send).
  const track = useCallback(
    (kind: TelemetryKind, data?: Record<string, unknown>) => enqueue(kind, data),
    [enqueue],
  )

  // Public: the participant posted a message — this is the ONLY thing that
  // resets the idle timer and hides the reminder.
  const noteActivity = useCallback(() => {
    lastMessageRef.current = Date.now()
    setIdlePromptVisible(false)
  }, [])

  const dismissIdlePrompt = useCallback(() => {
    // Hide the banner but keep counting: if the participant still doesn't post,
    // it re-appears after another idle window.
    setIdlePromptVisible(false)
  }, [])

  const flush = useCallback(
    (useBeacon = false) => {
      if (!sessionId || queueRef.current.length === 0) return
      const batch = queueRef.current
      queueRef.current = []
      sendTelemetry(sessionId, batch, useBeacon)
    },
    [sessionId],
  )

  // Event listeners for visibility / focus / activity.
  useEffect(() => {
    if (!sessionId) return
    if (!trackingEnabled && !idleEnabled) return

    // NOTE: none of these reset the idle timer — only posting a message does.
    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        enqueue("tab_hidden", { is_visible: false })
        flush(true) // may be backgrounded; use beacon
      } else {
        enqueue("tab_visible", { is_visible: true })
      }
    }
    const onFocus = () => enqueue("window_focus")
    const onBlur = () => enqueue("window_blur")
    const onMouseMove = () => {
      hadMouseRef.current = true
    }
    const onKeyDown = () => {
      hadKeyboardRef.current = true
    }
    const onPageHide = () => {
      enqueue("page_unload")
      flush(true)
    }

    document.addEventListener("visibilitychange", onVisibility)
    window.addEventListener("focus", onFocus)
    window.addEventListener("blur", onBlur)
    window.addEventListener("mousemove", onMouseMove, { passive: true })
    window.addEventListener("keydown", onKeyDown)
    window.addEventListener("pagehide", onPageHide)

    return () => {
      document.removeEventListener("visibilitychange", onVisibility)
      window.removeEventListener("focus", onFocus)
      window.removeEventListener("blur", onBlur)
      window.removeEventListener("mousemove", onMouseMove)
      window.removeEventListener("keydown", onKeyDown)
      window.removeEventListener("pagehide", onPageHide)
    }
  }, [sessionId, trackingEnabled, idleEnabled, enqueue, flush])

  // Telemetry heartbeat: periodic activity summary.
  useEffect(() => {
    if (!sessionId || !trackingEnabled) return
    const heartbeat = setInterval(() => {
      enqueue("activity", {
        is_visible: document.visibilityState === "visible",
        had_mouse_move: hadMouseRef.current,
        had_keyboard: hadKeyboardRef.current,
      })
      hadMouseRef.current = false
      hadKeyboardRef.current = false
    }, HEARTBEAT_MS)
    return () => clearInterval(heartbeat)
  }, [sessionId, trackingEnabled, enqueue])

  // Idle check: fire when the participant hasn't posted a message for
  // `idleSeconds`. Re-arms on each fire, so it keeps reminding (and logging)
  // every idle window until they post.
  useEffect(() => {
    if (!sessionId || !idleEnabled) return
    lastMessageRef.current = Date.now()
    const tick = setInterval(() => {
      if (Date.now() - lastMessageRef.current >= idleSeconds * 1000) {
        lastMessageRef.current = Date.now()
        setIdlePromptVisible(true)
        enqueue("idle_prompt_shown", { idle_seconds: idleSeconds })
      }
    }, IDLE_CHECK_MS)
    return () => clearInterval(tick)
  }, [sessionId, idleEnabled, idleSeconds, enqueue])

  // Flusher: periodically ship queued telemetry.
  useEffect(() => {
    if (!sessionId) return
    if (!trackingEnabled && !idleEnabled) return
    const flusher = setInterval(() => flush(false), FLUSH_MS)
    return () => {
      clearInterval(flusher)
      flush(false)
    }
  }, [sessionId, trackingEnabled, idleEnabled, flush])

  return { track, noteActivity, idlePromptVisible, dismissIdlePrompt }
}
