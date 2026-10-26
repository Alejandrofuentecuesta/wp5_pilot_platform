import { adminFetch } from "./admin-api"

export interface ParticipantTraits {
  opinion_strength: "automatic" | "moderate" | "firm"
  topic_knowledge: "automatic" | "low" | "medium" | "high"
  style: "automatic" | "brief" | "conversational" | "argumentative"
  activity: "automatic" | "observer" | "regular" | "active"
}

export interface SyntheticRequest {
  source_experiment_id: string
  groups: string[]
  sessions_per_group: number
  concurrency: number
  duration_minutes: number
  seed: number
  seed_mode?: "automatic" | "fixed"
  stance: "seeded_balanced" | "balanced" | "pro_topic" | "anti_topic"
  participant_provider: string
  participant_model: string
  participant_profile: string
  vary_participants?: boolean
  participant_traits?: ParticipantTraits
  participant_interval_seconds: number
  max_participant_calls: number
  confirm_api_usage: boolean
}

export interface SyntheticItem {
  index: number
  group: string
  seed: number
  stance: string
  status: string
  session_id: string | null
  participant_calls: number
  messages: number
  participant?: {
    version: number
    mode: "fixed" | "automatic"
    base_profile: string
    profile: string
    traits: Record<string, string>
    interval_seconds: number
    jitter_fraction: number
  }
  end_reason?: string
  error?: string
}

export interface SyntheticBatch {
  batch_id: string
  experiment_id: string
  source_experiment_id: string
  status: string
  created_at: string
  request: SyntheticRequest
  items: SyntheticItem[]
  error?: string | null
}

async function result<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${response.status})`)
  }
  return response.json()
}

export async function getSyntheticBatches(key: string): Promise<SyntheticBatch[]> {
  const body = await result<{ batches: SyntheticBatch[] }>(await adminFetch("/admin/synthetic-batches", key))
  return body.batches
}

export async function startSyntheticBatch(key: string, request: SyntheticRequest) {
  return result<{ batch_id: string; experiment_id: string; status: string }>(
    await adminFetch("/admin/synthetic-batches", key, { method: "POST", body: JSON.stringify(request) }),
  )
}

export async function cancelSyntheticBatch(key: string, batchId: string) {
  return result<{ status: string }>(await adminFetch(`/admin/synthetic-batches/${encodeURIComponent(batchId)}/cancel`, key, { method: "POST" }))
}
