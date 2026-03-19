import type { SimulationConfig, ExperimentalConfig, TokenConfig } from "../../../lib/admin-types"

interface StepReviewProps {
  experimentId: string
  startsAt: string
  endsAt: string
  simulation: SimulationConfig
  experimental: ExperimentalConfig
  tokens: TokenConfig
  saveResult: string
  saveError: string
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-admin-surface rounded-lg border border-admin-border p-5 space-y-3">
      <h3 className="text-sm font-semibold text-admin-muted uppercase tracking-wider">{title}</h3>
      {children}
    </div>
  )
}

function KV({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex justify-between text-sm py-1 border-b border-admin-border/50 last:border-0">
      <span className="text-admin-muted">{label}</span>
      <span className="text-admin-text font-medium">{String(value)}</span>
    </div>
  )
}

export default function StepReview({
  experimentId,
  startsAt,
  endsAt,
  simulation,
  experimental,
  tokens,
  saveResult,
  saveError,
}: StepReviewProps) {
  const totalTokens = Object.values(tokens.groups).reduce((sum, arr) => sum + arr.length, 0)
  const groupCount = Object.keys(experimental.groups).length

  return (
    <div className="space-y-6 pb-16">
      <div>
        <h2 className="text-lg font-semibold text-admin-text">Review Configuration</h2>
        <p className="text-sm text-admin-muted mt-1">
          Review all settings before saving. Once saved, this experiment&apos;s configuration cannot be changed.
          To use different settings, create a new experiment.
        </p>
      </div>

      {saveResult && (
        <div className="bg-admin-pastel-green border border-admin-pastel-green-text/20 rounded-lg px-4 py-3">
          <p className="text-sm text-admin-pastel-green-text">{saveResult}</p>
        </div>
      )}

      {saveError && (
        <div className="bg-admin-danger-soft border border-admin-danger-border rounded-lg px-4 py-3">
          <p className="text-sm text-admin-danger-text">{saveError}</p>
        </div>
      )}

      <Section title="Experiment">
        <KV label="Experiment ID" value={experimentId || "(not set)"} />
        <KV label="Starts at" value={startsAt ? new Date(startsAt).toLocaleString() : "(not set)"} />
        <KV label="Ends at" value={endsAt ? new Date(endsAt).toLocaleString() : "(not set)"} />
        <KV label="Completion redirect" value={experimental.redirect_url || "(built-in thank-you page)"} />
      </Section>

      <Section title="Session & Agents">
        <KV label="Duration" value={`${simulation.session_duration_minutes} min`} />
        <KV label="Agents" value={`${simulation.num_agents} (${simulation.agent_names.join(", ")})`} />
        <KV label="Messages/min" value={simulation.messages_per_minute} />
        <KV label="Evaluate interval" value={simulation.evaluate_interval} />
        <KV label="Action window" value={simulation.action_window_size} />
        <KV label="Performer memory" value={simulation.performer_memory_size} />
        <KV label="Random seed" value={simulation.random_seed} />
      </Section>

      <Section title="LLM Pipeline">
        <div className="grid grid-cols-3 gap-4 text-xs">
          {(["director", "performer", "moderator"] as const).map((role) => {
            const provider = simulation[`${role}_llm_provider` as keyof SimulationConfig] as string
            const model = simulation[`${role}_llm_model` as keyof SimulationConfig] as string
            const temp = simulation[`${role}_temperature` as keyof SimulationConfig] as number
            const topP = simulation[`${role}_top_p` as keyof SimulationConfig] as number
            const maxTok = simulation[`${role}_max_tokens` as keyof SimulationConfig] as number
            return (
              <div key={role} className="space-y-1">
                <p className="font-semibold text-admin-text capitalize">{role}</p>
                <p className="text-admin-muted">{provider}</p>
                <p className="text-admin-muted font-mono text-[11px] break-all">{model}</p>
                <p className="text-admin-faint">temp={temp} top_p={topP} max={maxTok}</p>
              </div>
            )
          })}
        </div>
      </Section>

      <Section title="Treatment Groups">
        <KV label="Chatroom context" value={experimental.chatroom_context.slice(0, 80) + (experimental.chatroom_context.length > 80 ? "..." : "")} />
        <KV label="Incivility framework" value={experimental.incivility_framework ? experimental.incivility_framework.slice(0, 80) + (experimental.incivility_framework.length > 80 ? "..." : "") : "(not set)"} />
        <KV label="Ecological validity" value={experimental.ecological_validity_criteria.slice(0, 80) + (experimental.ecological_validity_criteria.length > 80 ? "..." : "")} />
        <div className="space-y-3 mt-2">
          {Object.entries(experimental.groups).map(([name, group]) => (
            <div key={name} className="border border-admin-border rounded-lg p-3">
              <p className="text-sm font-mono font-semibold text-admin-text">{name}</p>
              <p className="text-xs text-admin-faint">features: {(group.features ?? []).join(", ") || "none"}</p>
              <p className="text-xs text-admin-muted mt-1 line-clamp-2">{group.internal_validity_criteria}</p>
              {group.seed && (
                <p className="text-xs text-admin-faint mt-1">Seed: {group.seed.headline}</p>
              )}
            </div>
          ))}
        </div>
      </Section>

      <Section title="Tokens">
        <KV label="Total tokens" value={totalTokens} />
        <KV label="Groups" value={groupCount} />
        {Object.entries(tokens.groups).map(([group, toks]) => (
          <KV key={group} label={group} value={`${toks.length} tokens`} />
        ))}
        {totalTokens === 0 && (
          <p className="text-xs text-amber-600">No tokens generated yet. Go to Step 5 to generate them.</p>
        )}
      </Section>

    </div>
  )
}
