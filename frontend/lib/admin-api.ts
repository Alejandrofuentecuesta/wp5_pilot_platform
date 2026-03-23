/* Admin API client — all requests include X-Admin-Key header. */

import { API_BASE } from "./constants"
import type { AdminMeta, SessionSummary, SimulationConfig, ExperimentalConfig, TokenConfig, TokenGroupStats, TestLLMResult, ComplianceStats } from "./admin-types"

async function adminFetch(
  path: string,
  adminKey: string,
  options: RequestInit = {},
): Promise<Response> {
  return fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Admin-Key": adminKey,
      ...(options.headers || {}),
    },
  })
}

export async function verifyPassphrase(key: string): Promise<boolean> {
  try {
    const res = await adminFetch("/admin/verify", key)
    return res.ok
  } catch {
    return false
  }
}

export async function getMeta(key: string): Promise<AdminMeta> {
  const res = await adminFetch("/admin/meta", key)
  if (!res.ok) throw new Error("Failed to load platform metadata")
  return res.json()
}

export async function testLlm(
  key: string,
  params: {
    provider: string
    model: string
    temperature?: number | null
    top_p?: number | null
    max_tokens?: number
    bsc_model_version?: string
  },
): Promise<TestLLMResult> {
  const res = await adminFetch("/admin/test-llm", key, {
    method: "POST",
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Test request failed" }))
    throw new Error(err.detail || "Test request failed")
  }
  return res.json()
}

export async function getExperimentConfig(
  key: string,
  experimentId: string,
): Promise<{
  experiment_id: string
  description: string
  config: { simulation: SimulationConfig; experimental: ExperimentalConfig }
  created_at: string
  starts_at: string | null
  ends_at: string | null
}> {
  const res = await adminFetch(`/admin/config/${encodeURIComponent(experimentId)}`, key)
  if (!res.ok) throw new Error("Failed to load experiment config")
  return res.json()
}

export async function saveConfig(
  key: string,
  config: {
    experiment_id: string
    description?: string
    simulation: SimulationConfig
    experimental: ExperimentalConfig
    tokens: TokenConfig
    starts_at?: string | null
    ends_at?: string | null
  },
): Promise<{ status: string; experiment_id: string }> {
  const res = await adminFetch("/admin/config", key, {
    method: "POST",
    body: JSON.stringify(config),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Save failed" }))
    throw new Error(err.detail || "Save failed")
  }
  return res.json()
}

export async function updateConfig(
  key: string,
  experimentId: string,
  config: {
    description?: string
    simulation: SimulationConfig
    experimental: ExperimentalConfig
    starts_at?: string | null
    ends_at?: string | null
  },
): Promise<{ status: string; experiment_id: string }> {
  const res = await adminFetch(`/admin/config/${encodeURIComponent(experimentId)}`, key, {
    method: "PUT",
    body: JSON.stringify(config),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Update failed" }))
    throw new Error(err.detail || "Update failed")
  }
  return res.json()
}

export async function activateExperiment(
  key: string,
  experimentId: string,
): Promise<{ status: string; experiment_id: string }> {
  const res = await adminFetch(`/admin/experiment/${encodeURIComponent(experimentId)}/activate`, key, {
    method: "POST",
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Activation failed" }))
    throw new Error(err.detail || "Activation failed")
  }
  return res.json()
}

export async function pauseExperiment(
  key: string,
  experimentId: string,
): Promise<{ status: string; experiment_id: string }> {
  const res = await adminFetch(`/admin/experiment/${encodeURIComponent(experimentId)}/pause`, key, {
    method: "POST",
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Pause failed" }))
    throw new Error(err.detail || "Pause failed")
  }
  return res.json()
}

export async function resumeExperiment(
  key: string,
  experimentId: string,
): Promise<{ status: string; experiment_id: string }> {
  const res = await adminFetch(`/admin/experiment/${encodeURIComponent(experimentId)}/resume`, key, {
    method: "POST",
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Resume failed" }))
    throw new Error(err.detail || "Resume failed")
  }
  return res.json()
}

export async function generateTokens(
  key: string,
  participantsPerGroup: number,
  groups: string[],
): Promise<{ tokens: Record<string, string[]>; total: number }> {
  const res = await adminFetch("/admin/tokens/generate", key, {
    method: "POST",
    body: JSON.stringify({
      participants_per_group: participantsPerGroup,
      groups,
    }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Generation failed" }))
    throw new Error(err.detail || "Generation failed")
  }
  return res.json()
}

export interface ExperimentSummary {
  experiment_id: string
  description: string
  created_at: string | null
  starts_at: string | null
  ends_at: string | null
  paused: boolean
  sessions: number
  messages: number
  tokens: number
  tokens_used: number
}

export async function listExperiments(
  key: string,
): Promise<{ experiments: ExperimentSummary[]; active_experiment_id: string }> {
  const res = await adminFetch("/admin/experiments", key)
  if (!res.ok) throw new Error("Failed to list experiments")
  return res.json()
}

export async function listSessions(
  key: string,
  experimentId?: string,
): Promise<{ sessions: SessionSummary[] }> {
  const params = experimentId ? `?experiment_id=${encodeURIComponent(experimentId)}` : ""
  const res = await adminFetch(`/admin/sessions${params}`, key)
  if (!res.ok) throw new Error("Failed to list sessions")
  return res.json()
}

export async function getTokenStats(
  key: string,
  experimentId?: string,
): Promise<{ groups: TokenGroupStats[] }> {
  const params = experimentId ? `?experiment_id=${encodeURIComponent(experimentId)}` : ""
  const res = await adminFetch(`/admin/tokens/stats${params}`, key)
  if (!res.ok) throw new Error("Failed to load token stats")
  return res.json()
}

export interface AdminEvent {
  id: number
  session_id: string
  event_type: string
  occurred_at: string
  data: Record<string, unknown>
}

export interface SessionMessageForEvaluation {
  message_id: string
  sender: string
  content: string
  timestamp: string
  manual_evaluation?: {
    incivility: boolean
    hate_speech: boolean
    threats_to_dem_freedom: boolean
    impoliteness: boolean
    alignment: string
    human_like: string
    other: string
    updated_at?: string | null
  } | null
}

export async function getEvents(
  key: string,
  experimentId: string,
  afterId: number = 0,
  limit: number = 200,
): Promise<{ events: AdminEvent[] }> {
  const params = new URLSearchParams({
    experiment_id: experimentId,
    after_id: String(afterId),
    limit: String(limit),
  })
  const res = await adminFetch(`/admin/events?${params}`, key)
  if (!res.ok) throw new Error("Failed to load events")
  return res.json()
}

export async function getSessionMessagesForEvaluation(
  key: string,
  sessionId: string,
  experimentId: string,
): Promise<{ messages: SessionMessageForEvaluation[] }> {
  const params = new URLSearchParams({ experiment_id: experimentId })
  const res = await adminFetch(`/admin/session/${encodeURIComponent(sessionId)}/messages?${params}`, key)
  if (!res.ok) throw new Error("Failed to load session messages")
  return res.json()
}

export async function saveSessionEvaluation(
  key: string,
  sessionId: string,
  experimentId: string,
  rows: Array<{
    message_id: string
    incivility: boolean
    hate_speech: boolean
    threats_to_dem_freedom: boolean
    impoliteness: boolean
    alignment: string
    human_like: string
    other: string
  }>,
): Promise<{ status: string; session_id: string; saved_rows: number }> {
  const params = new URLSearchParams({ experiment_id: experimentId })
  const res = await adminFetch(`/admin/session/${encodeURIComponent(sessionId)}/evaluation?${params}`, key, {
    method: "PUT",
    body: JSON.stringify({ rows }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to save evaluation" }))
    throw new Error(err.detail || "Failed to save evaluation")
  }
  return res.json()
}

export async function downloadEvaluationSummaryCSV(
  key: string,
  experimentId: string,
): Promise<void> {
  const res = await adminFetch(`/admin/evaluations/summary-csv/${encodeURIComponent(experimentId)}`, key)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Summary CSV export failed" }))
    throw new Error(err.detail || "Summary CSV export failed")
  }

  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = `${experimentId}_evaluation_summary.csv`
  a.click()
  URL.revokeObjectURL(url)
}

export async function resetSessions(
  key: string,
  experimentId: string,
): Promise<{ status: string; experiment_id: string; sessions_deleted: number }> {
  const res = await adminFetch("/admin/reset-sessions", key, {
    method: "POST",
    body: JSON.stringify({ experiment_id: experimentId }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Reset failed" }))
    throw new Error(err.detail || "Reset failed")
  }
  return res.json()
}

export async function cloneExperiment(
  key: string,
  sourceId: string,
  newId: string,
  description?: string,
): Promise<{ status: string; source_experiment_id: string; new_experiment_id: string }> {
  const res = await adminFetch(`/admin/experiment/${encodeURIComponent(sourceId)}/clone`, key, {
    method: "POST",
    body: JSON.stringify({ new_experiment_id: newId, description }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Clone failed" }))
    throw new Error(err.detail || "Clone failed")
  }
  return res.json()
}

export async function downloadSessionsCSV(
  key: string,
  experimentId: string,
): Promise<void> {
  const res = await adminFetch(`/admin/sessions/csv/${encodeURIComponent(experimentId)}`, key)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "CSV export failed" }))
    throw new Error(err.detail || "CSV export failed")
  }

  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = `${experimentId}_sessions.csv`
  a.click()
  URL.revokeObjectURL(url)
}

export async function deleteExperiment(
  key: string,
  experimentId: string,
): Promise<{ status: string; experiment_id: string }> {
  const res = await adminFetch("/admin/reset-db", key, {
    method: "POST",
    body: JSON.stringify({ experiment_id: experimentId }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Delete failed" }))
    throw new Error(err.detail || "Delete failed")
  }
  return res.json()
}

export async function fetchPromptDefaults(key: string): Promise<Record<string, string>> {
  const res = await adminFetch("/admin/prompt-defaults", key)
  if (!res.ok) throw new Error("Failed to load prompt defaults")
  return res.json()
}

export async function getComplianceStats(
  key: string,
  experimentId: string,
): Promise<ComplianceStats> {
  const res = await adminFetch(`/admin/experiment/${encodeURIComponent(experimentId)}/compliance`, key)
  if (!res.ok) throw new Error("Failed to load compliance stats")
  return res.json()
}
