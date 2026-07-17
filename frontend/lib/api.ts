import { API_BASE } from "./constants"
import type { ParticipantStance, SessionIntakeResponse, SessionStartResponse, QueueJoinResponse } from "./types"

export async function previewSessionIntake(
  token: string,
): Promise<SessionIntakeResponse> {
  const res = await fetch(`${API_BASE}/session/intake`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  })
  if (!res.ok) throw new Error("Invalid token")
  return res.json()
}

export class AtCapacityError extends Error {
  constructor() {
    super("at_capacity")
    this.name = "AtCapacityError"
  }
}

export async function startSession(
  token: string,
  participantName?: string,
  participantStance?: ParticipantStance,
): Promise<SessionStartResponse> {
  const res = await fetch(`${API_BASE}/session/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, participant_name: participantName || null, participant_stance: participantStance }),
  })
  if (res.status === 503) {
    const body = await res.json().catch(() => ({}))
    if (body?.detail?.reason === "at_capacity") {
      throw new AtCapacityError()
    }
  }
  if (!res.ok) throw new Error("Invalid token")
  return res.json()
}

export async function joinQueue(
  token: string,
  participantName?: string,
  participantStance?: ParticipantStance,
): Promise<QueueJoinResponse> {
  const res = await fetch(`${API_BASE}/queue/join`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, participant_name: participantName || null, participant_stance: participantStance }),
  })
  if (!res.ok) throw new Error(`Queue join failed: ${res.status}`)
  return res.json()
}

export async function updateParticipantStance(
  sessionId: string,
  participantStance: ParticipantStance,
): Promise<{ session_id: string; participant_stance: ParticipantStance }> {
  const res = await fetch(`${API_BASE}/session/${sessionId}/participant-stance`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ participant_stance: participantStance }),
  })
  if (!res.ok) throw new Error("Failed to update participant stance")
  return res.json()
}

export function sendTelemetry(
  sessionId: string,
  events: Array<{ kind: string; at: string; data?: Record<string, unknown> }>,
  useBeacon = false,
): void {
  if (events.length === 0) return
  const url = `${API_BASE}/session/${sessionId}/telemetry`
  const body = JSON.stringify({ events })
  // sendBeacon survives page unload / tab backgrounding; fall back to fetch.
  if (useBeacon && typeof navigator !== "undefined" && navigator.sendBeacon) {
    try {
      navigator.sendBeacon(url, new Blob([body], { type: "application/json" }))
      return
    } catch {
      // fall through to fetch
    }
  }
  fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    keepalive: true,
  }).catch(() => {
    // Telemetry is best-effort; never surface errors to the participant.
  })
}

export async function likeMessage(
  sessionId: string,
  messageId: string,
  user: string,
) {
  const res = await fetch(
    `${API_BASE}/session/${sessionId}/message/${messageId}/like`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user }),
    },
  )
  if (!res.ok) throw new Error("Network error")
  return res.json()
}

export async function reportMessage(
  sessionId: string,
  messageId: string,
  user: string,
  block: boolean,
) {
  const res = await fetch(
    `${API_BASE}/session/${sessionId}/message/${messageId}/report`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user, block }),
    },
  )
  if (!res.ok) throw new Error("Network error")
  return res.json()
}
