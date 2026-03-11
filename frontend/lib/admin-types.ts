/* TypeScript interfaces for admin config shapes. */

export interface SimulationConfig {
  random_seed: number
  session_duration_minutes: number
  num_agents: number
  agent_names: string[]
  agent_personas: string[]  // Personality descriptions for each agent
  messages_per_minute: number
  max_concurrent_turns: number
  director_llm_provider: string
  director_llm_model: string
  director_temperature: number
  director_top_p: number
  director_max_tokens: number
  performer_llm_provider: string
  performer_llm_model: string
  performer_temperature: number
  performer_top_p: number
  performer_max_tokens: number
  moderator_llm_provider: string
  moderator_llm_model: string
  moderator_temperature: number
  moderator_top_p: number
  moderator_max_tokens: number
  classifier_llm_provider: string
  classifier_llm_model: string
  classifier_temperature: number
  classifier_top_p: number
  classifier_max_tokens: number
  classifier_prompt_template: string
  context_window_size: number
  llm_concurrency_limit: number
}

export interface SeedArticle {
  type: string
  headline: string
  source: string
  body: string
}

export interface TreatmentGroup {
  features: string[]
  treatment: string
  seed?: SeedArticle
}

export interface ExperimentalConfig {
  chatroom_context: string
  redirect_url: string
  groups: Record<string, TreatmentGroup>
}

export interface TokenConfig {
  groups: Record<string, string[]>
}

export interface FeatureMeta {
  id: string
  label: string
  description: string
}

export interface ProviderParamsMeta {
  temperature?: boolean
  top_p?: boolean
  max_tokens?: boolean
  mutual_exclusion?: string[]
}

export interface AdminMeta {
  available_features: FeatureMeta[]
  llm_providers: string[]
  provider_models: Record<string, string[]>
  provider_params: Record<string, ProviderParamsMeta>
}

export interface TestLLMResult {
  ok: boolean
  call_params: Record<string, unknown>
  prompt: string
  response?: string | null
  error?: string | null
  warnings: string[]
}

// AdminConfig is no longer used — config is stored per-experiment in the DB.
// The wizard creates new experiments with fresh defaults from the frontend.

export interface SessionSummary {
  session_id: string
  treatment_group: string
  token: string
  status: "pending" | "active" | "ended" | "crashed"
  started_at: string | null
  ended_at: string | null
  end_reason: string | null
  message_count: number
  agent_message_count: number
  incivil_message_count: number
  incivil_classified_count: number
  like_minded_message_count: number
  like_minded_classified_count: number
  incivil_pct: number | null
  like_minded_pct: number | null
}

export interface TokenGroupStats {
  group: string
  total: number
  used: number
}
