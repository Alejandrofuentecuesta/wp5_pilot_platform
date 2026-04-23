"use client"

import { useEffect, useState } from "react"
import type { SimulationConfig } from "../../../lib/admin-types"
import { normalizeAgentNames } from "../../../lib/agent-name-options"

function AgentModeHelpModal({ onClose }: { onClose: () => void }) {
  return (
    <div
      className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center px-4 py-6 overflow-y-auto"
      role="dialog"
      aria-modal="true"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="w-full max-w-2xl rounded-2xl border border-admin-border bg-admin-surface shadow-2xl overflow-hidden">
        <div className="h-1 bg-admin-accent" />
        <div className="p-6 space-y-5">
          <div className="flex items-start justify-between gap-4">
            <h2 className="text-lg font-semibold text-admin-text">Agent Mode — How it works</h2>
            <button
              type="button"
              onClick={onClose}
              className="shrink-0 rounded-full border border-admin-border px-3 py-1 text-xs font-medium text-admin-muted hover:text-admin-text hover:border-admin-accent transition-colors"
            >
              Close
            </button>
          </div>

          <div className="space-y-5 text-sm text-admin-text">

            {/* Prompt-based */}
            <div className="rounded-xl border border-admin-border bg-admin-surface-alt p-4 space-y-2">
              <div className="font-semibold text-admin-text">Prompt-based mode</div>
              <p className="text-admin-muted leading-relaxed">
                You define a fixed set of agents (names + optional personas) that is shared across all treatment groups.
                The Director LLM is responsible for shaping each agent&apos;s stance and incivility turn-by-turn through
                its validity criteria instructions — there are no pre-set trait labels on the agents themselves.
              </p>
              <div className="mt-2">
                <div className="text-xs font-semibold text-admin-muted uppercase tracking-wider mb-1">Workflow</div>
                <ol className="list-decimal list-inside space-y-1 text-admin-muted text-xs">
                  <li>Create agents in the <strong>Session</strong> step (names, optional personas).</li>
                  <li>Set validity criteria per treatment in the <strong>Treatments</strong> step — these tell the Director what tone and stance the conversation should have.</li>
                  <li>At runtime, the Director reads the criteria each turn and picks the best agent action to satisfy them. It adjusts dynamically as the conversation evolves.</li>
                </ol>
              </div>
              <p className="text-xs text-admin-muted mt-1">
                <strong>Best for:</strong> exploratory experiments, small agent sets, or when you want the LLM to handle all stance/incivility management through prompting.
              </p>
            </div>

            {/* Pool-based */}
            <div className="rounded-xl border border-admin-border bg-admin-surface-alt p-4 space-y-2">
              <div className="font-semibold text-admin-text">Agent pool mode</div>
              <p className="text-admin-muted leading-relaxed">
                You pre-define a bank of agents with fixed trait labels (<em>stance</em>, <em>incivility</em>, <em>ideology</em>).
                Each treatment selects a candidate subset from the pool. At session start, the backend picks the final
                live lineup based on the participant&apos;s self-report and the treatment&apos;s quota targets
                (<code>LIKEMINDED_TARGET</code> / <code>INCIVILITY_TARGET</code>).
              </p>
              <div className="mt-2">
                <div className="text-xs font-semibold text-admin-muted uppercase tracking-wider mb-1">Workflow</div>
                <ol className="list-decimal list-inside space-y-1 text-admin-muted text-xs">
                  <li>Build the agent pool in the <strong>Treatments</strong> step — assign each agent a stance, incivility level, and persona.</li>
                  <li>Per treatment, pick the candidate agent IDs (<em>pool_agent_ids</em>) the backend may draw from.</li>
                  <li>Set <code>LIKEMINDED_TARGET</code> and <code>INCIVILITY_TARGET</code> percentages in the validity criteria.</li>
                  <li>When a participant joins, the backend reads their self-report (in favor of the measure / against the measure / in favor of the topic but against the measure) and selects the agents that best satisfy the treatment quotas.</li>
                  <li>The Director still orchestrates turn-by-turn, but the agents&apos; trait labels are fixed — no prompting is needed to enforce stance or incivility.</li>
                </ol>
              </div>
              <p className="text-xs text-admin-muted mt-1">
                <strong>Best for:</strong> factorial designs where you need precise control over like-mindedness and incivility exposure across conditions (e.g., a 3×3 incivility × like-mindedness experiment).
              </p>
            </div>

            {/* Shared pipeline */}
            <div className="rounded-xl border border-admin-border bg-admin-surface-alt p-4 space-y-2">
              <div className="font-semibold text-admin-text">Shared pipeline (both modes)</div>
              <p className="text-admin-muted leading-relaxed text-xs">
                Regardless of mode, every agent turn runs the same <strong>Director → Performer → Moderator</strong> pipeline:
              </p>
              <ol className="list-decimal list-inside space-y-1 text-admin-muted text-xs">
                <li><strong>Director Update</strong> — revises the last agent&apos;s profile based on what they just said.</li>
                <li><strong>Director Evaluate</strong> — scores the recent conversation against internal and ecological validity criteria.</li>
                <li><strong>Director Action</strong> — chooses which agent acts next and what instruction to give them.</li>
                <li><strong>Performer</strong> — generates the actual message following the instruction.</li>
                <li><strong>Moderator</strong> — extracts the clean message content and removes any meta-commentary.</li>
                <li><strong>Classifier</strong> — labels the message (stance, incivility) for research logging.</li>
              </ol>
            </div>

          </div>
        </div>
      </div>
    </div>
  )
}

interface StepSessionProps {
  config: SimulationConfig
  onChange: (updates: Partial<SimulationConfig>) => void
  touched: boolean
}

const inputClass = "w-full px-3 py-2 border border-admin-border rounded-lg text-sm bg-admin-surface text-admin-text focus:outline-none focus:border-admin-accent focus:ring-1 focus:ring-admin-accent/30"

// Example personas for a political incivility experiment (Spanish context).
// Each entry maps to an agent slot by index (wraps if there are more agents than examples).
const EXAMPLE_PERSONAS = [
  (name: string) =>
    `${name} es una persona progresista de unos 35 años, apasionada por los derechos sociales y la justicia medioambiental. Comunica de manera directa y emocional, con tendencia a apelar a la solidaridad y al bien común. Cuando se siente atacada, puede volverse sarcástica pero raramente pierde la compostura del todo.`,
  (name: string) =>
    `${name} es un hombre conservador de unos 50 años, con visión pragmática y orientada a la economía. Desconfía de la intervención estatal y valora la responsabilidad individual. Su tono suele ser firme y algo condescendiente cuando debate con quienes no comparten su visión.`,
  (name: string) =>
    `${name} es una persona de centro, de unos 28 años, que intenta ver varios ángulos de los problemas. Sin embargo, tiene un umbral bajo de paciencia ante los argumentos que percibe como simplistas. Usa la ironía con frecuencia y puede escalar el tono si se siente ignorada o ridiculizada.`,
  (name: string) =>
    `${name} es una persona de izquierda radical, en torno a los 40 años, que considera que el sistema político actual está roto. Su comunicación es combativa y no evita el conflicto; a veces recurre a la provocación deliberada para poner a prueba las convicciones de los demás.`,
  (name: string) =>
    `${name} es una persona moderada de unos 45 años, con formación universitaria y un estilo argumentativo metódico. Suele pedir evidencias antes de pronunciarse y puede mostrarse distante o cortante si percibe que la conversación se está desviando hacia la demagogia.`,
]

export default function StepSession({ config, onChange, touched }: StepSessionProps) {
  const [showPersonas, setShowPersonas] = useState(false)
  const [showAgentModeHelp, setShowAgentModeHelp] = useState(false)

  useEffect(() => {
    if ((config.agent_personas || []).some((persona) => persona.trim().length > 0)) {
      setShowPersonas(true)
    }
  }, [config.agent_personas])

  const updateAgentName = (index: number, value: string) => {
    const names = [...config.agent_names]
    names[index] = value
    onChange({ agent_names: names })
  }

  const updateAgentPersona = (index: number, value: string) => {
    const personas = [...(config.agent_personas || [])]
    while (personas.length < config.agent_names.length) personas.push("")
    personas[index] = value
    onChange({ agent_personas: personas })
  }

  const handleNumAgentsChange = (n: number) => {
    const names = normalizeAgentNames(n, config.agent_names)
    const personas = [...(config.agent_personas || [])]
    while (personas.length < n) personas.push("")
    personas.length = n
    onChange({ num_agents: n, agent_names: names, agent_personas: personas })
  }

  const loadExamplePersonas = () => {
    const personas = config.agent_names.map((name, i) => {
      const builder = EXAMPLE_PERSONAS[i % EXAMPLE_PERSONAS.length]
      return builder(name || `Agente ${i + 1}`)
    })
    onChange({ agent_personas: personas })
    setShowPersonas(true)
  }

  const agentNameErrors = config.agent_names.map((name, i) => {
    if (!name.trim()) return "Required"
    if (config.agent_names.some((other, j) => j !== i && other.trim() === name.trim())) return "Duplicate"
    return null
  })

  return (
    <div className="space-y-6">
      {showAgentModeHelp && <AgentModeHelpModal onClose={() => setShowAgentModeHelp(false)} />}

      <div>
        <h2 className="text-lg font-semibold text-admin-text">Session & Agents</h2>
        <p className="text-sm text-admin-muted mt-1">
          Configure session timing, agent count, and message pacing.
        </p>
      </div>

      {/* Agent mode toggle */}
      <div className="bg-admin-surface rounded-lg border border-admin-border p-5 space-y-3">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-admin-muted uppercase tracking-wider">Agent Mode</h3>
          <button
            type="button"
            onClick={() => setShowAgentModeHelp(true)}
            className="flex items-center justify-center w-4 h-4 rounded-full border border-admin-muted text-admin-muted hover:border-admin-accent hover:text-admin-accent transition-colors text-[10px] font-bold leading-none flex-shrink-0"
            title="How does Agent Mode work?"
          >
            ?
          </button>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <button
            onClick={() => onChange({ agent_mode: "prompt" })}
            className={`px-4 py-3 rounded-lg border transition-colors text-left ${
              (config.agent_mode ?? "prompt") === "prompt"
                ? "border-admin-accent bg-admin-accent/10 text-admin-text"
                : "border-admin-border hover:border-admin-accent/50 text-admin-muted"
            }`}
          >
            <div className="font-medium text-sm">Prompt-based</div>
            <div className="text-xs mt-1 opacity-75">
              Director controls stance &amp; incivility via validity criteria prompts. Same agents for all treatments.
            </div>
          </button>
          <button
            onClick={() => onChange({ agent_mode: "pool" })}
            className={`px-4 py-3 rounded-lg border transition-colors text-left ${
              (config.agent_mode ?? "prompt") === "pool"
                ? "border-admin-accent bg-admin-accent/10 text-admin-text"
                : "border-admin-border hover:border-admin-accent/50 text-admin-muted"
            }`}
          >
            <div className="font-medium text-sm">Agent pool</div>
            <div className="text-xs mt-1 opacity-75">
              Pre-defined agents with fixed stance, ideology &amp; incivility. Each treatment selects agents from the pool, and the participant survey helps choose the final lineup.
            </div>
          </button>
        </div>
        {(config.agent_mode ?? "prompt") === "pool" && (
          <p className="text-xs text-admin-faint bg-admin-surface-alt border border-admin-border rounded p-3">
            In pool mode, agents are configured per-treatment in the <strong>Treatments</strong> step. The agent names/personas above are ignored — each treatment picks its own candidate agents from the experiment pool, and the participant survey helps the backend decide the final live lineup.
          </p>
        )}
      </div>

      <div className="bg-admin-surface rounded-lg border border-admin-border p-5 space-y-4">
        <h3 className="text-sm font-semibold text-admin-muted uppercase tracking-wider">Session</h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-admin-text mb-1">
              Duration (minutes)
            </label>
            <input
              type="number"
              min={1}
              value={config.session_duration_minutes}
              onChange={(e) => onChange({ session_duration_minutes: Math.max(1, parseInt(e.target.value) || 1) })}
              className={inputClass}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-admin-text mb-1">
              Random seed
            </label>
            <input
              type="number"
              value={config.random_seed}
              onChange={(e) => onChange({ random_seed: parseInt(e.target.value) || 0 })}
              className={inputClass}
            />
          </div>
        </div>
      </div>

      <div className="bg-admin-surface rounded-lg border border-admin-border p-5 space-y-4">
        <h3 className="text-sm font-semibold text-admin-muted uppercase tracking-wider">Agents</h3>
        <div>
          <label className="block text-sm font-medium text-admin-text mb-1">
            Number of agents
          </label>
          <input
            type="number"
            min={0}
            max={20}
            value={config.num_agents}
            onChange={(e) => handleNumAgentsChange(Math.max(0, parseInt(e.target.value) || 0))}
            className="w-24 px-3 py-2 border border-admin-border rounded-lg text-sm bg-admin-surface text-admin-text focus:outline-none focus:border-admin-accent focus:ring-1 focus:ring-admin-accent/30"
          />
        </div>
        {config.num_agents > 0 && (
          <>
            <div>
              <label className="block text-sm font-medium text-admin-text mb-2">
                Agent names
              </label>
              <p className="text-xs text-admin-faint mb-2">
                Names are auto-filled from a default list when you change the number of agents, but you can still edit them manually.
              </p>
              <div className="flex flex-wrap gap-2">
                {config.agent_names.map((name, i) => (
                  <div key={i} className="flex flex-col">
                    <input
                      type="text"
                      value={name}
                      onChange={(e) => updateAgentName(i, e.target.value)}
                      placeholder={`Agent ${i + 1}`}
                      className={`w-32 px-3 py-1.5 border rounded-lg text-sm bg-admin-surface text-admin-text focus:outline-none focus:ring-1 ${
                        touched && agentNameErrors[i]
                          ? "border-red-400 focus:border-red-400 focus:ring-red-400/30"
                          : "border-admin-border focus:border-admin-accent focus:ring-admin-accent/30"
                      }`}
                    />
                    {touched && agentNameErrors[i] && (
                      <span className="text-xs text-red-400 mt-0.5">{agentNameErrors[i]}</span>
                    )}
                  </div>
                ))}
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between gap-3 mb-2">
                <label className="block text-sm font-medium text-admin-text">
                  Agent personas (optional)
                </label>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={loadExamplePersonas}
                    className="text-xs font-medium border border-admin-accent/40 rounded-lg px-2.5 py-1 bg-admin-surface text-admin-accent hover:bg-admin-accent/10"
                    title="Fill in example personas suitable for a political incivility experiment"
                  >
                    Load examples
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowPersonas((prev) => !prev)}
                    className="text-xs font-medium border border-admin-border rounded-lg px-2.5 py-1 bg-admin-surface text-admin-muted hover:text-admin-text"
                  >
                    {showPersonas ? "Hide" : "Add"}
                  </button>
                </div>
              </div>
              <p className="text-xs text-admin-faint mb-3">
                Optional. If defined, each agent will use their persona to guide their writing style and political viewpoint. Click &ldquo;Load examples&rdquo; to see ready-made personas for a political discussion experiment.
              </p>
              {showPersonas && (
                <div className="space-y-3">
                  {config.agent_names.map((name, i) => (
                    <div key={i} className="flex flex-col">
                      <label className="text-xs font-medium text-admin-muted mb-1">
                        {name || `Agent ${i + 1}`}
                      </label>
                      <textarea
                        value={(config.agent_personas || [])[i] || ""}
                        onChange={(e) => updateAgentPersona(i, e.target.value)}
                        placeholder={`Describe ${name || `Agent ${i + 1}`}'s personality, background, communication style...`}
                        rows={2}
                        className={`${inputClass} resize-vertical text-xs`}
                      />
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </div>

      <div className="bg-admin-surface rounded-lg border border-admin-border p-5 space-y-4">
        <h3 className="text-sm font-semibold text-admin-muted uppercase tracking-wider">Pacing</h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-admin-text mb-1">
              Messages per minute
            </label>
            <input
              type="number"
              min={0}
              value={config.messages_per_minute}
              onChange={(e) => onChange({ messages_per_minute: Math.max(0, parseInt(e.target.value) || 0) })}
              className={inputClass}
            />
            <p className="text-xs text-admin-muted mt-1">
              Upper bound - actual rate will be slower, limited by the Director-&gt;Performer-&gt;Moderator pipeline latency.
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium text-admin-text mb-1">
              Validity check interval
            </label>
            <input
              type="number"
              min={1}
              value={config.evaluate_interval}
              onChange={(e) => onChange({ evaluate_interval: Math.max(1, parseInt(e.target.value) || 1) })}
              className={inputClass}
            />
            <p className="text-xs text-admin-faint mt-1">How often the Director re-evaluates validity criteria (in messages). Also sets the chat log length for the Evaluate call.</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-admin-text mb-1">
              Action window size
            </label>
            <input
              type="number"
              min={1}
              value={config.action_window_size}
              onChange={(e) => onChange({ action_window_size: Math.max(1, parseInt(e.target.value) || 1) })}
              className={inputClass}
            />
            <p className="text-xs text-admin-faint mt-1">Recent messages included in the Director Action call. Controls how much conversation context the Director sees when deciding the next action.</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-admin-text mb-1">
              Performer memory size
            </label>
            <input
              type="number"
              min={0}
              value={config.performer_memory_size}
              onChange={(e) => onChange({ performer_memory_size: Math.max(0, parseInt(e.target.value) || 0) })}
              className={inputClass}
            />
            <p className="text-xs text-admin-faint mt-1">Number of the performer&apos;s own recent messages included in its prompt. Helps avoid repetition. Set to 0 to disable.</p>
          </div>
        </div>

        {/* Parallel turns */}
        <div className="border-t border-admin-border pt-4">
          <div className="flex items-center justify-between">
            <div>
              <label className="block text-sm font-medium text-admin-text">
                Parallel pipelines
              </label>
              <p className="text-xs text-admin-faint mt-0.5">
                Run multiple Director&rarr;Performer&rarr;Moderator pipelines concurrently. Each pipeline makes independent API calls in parallel, reducing wait time. After each round, directors see the messages produced by all pipelines.
              </p>
            </div>
            <button
              onClick={() => onChange({ parallel_turns: (config.parallel_turns ?? 1) > 1 ? 1 : 2 })}
              className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors flex-shrink-0 ml-4 ${(config.parallel_turns ?? 1) > 1 ? "bg-admin-accent" : "bg-admin-border"}`}
            >
              <span className={`inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform ${(config.parallel_turns ?? 1) > 1 ? "translate-x-4" : "translate-x-1"}`} />
            </button>
          </div>
          {(config.parallel_turns ?? 1) > 1 && (
            <div className="mt-3">
              <label className="block text-xs font-medium text-admin-muted mb-1">
                Concurrent pipelines
              </label>
              <input
                type="number"
                min={2}
                max={4}
                value={config.parallel_turns ?? 2}
                onChange={(e) => onChange({ parallel_turns: Math.min(4, Math.max(2, parseInt(e.target.value) || 2)) })}
                className="w-20 px-3 py-1.5 border border-admin-border rounded-lg text-sm bg-admin-surface text-admin-text focus:outline-none focus:border-admin-accent focus:ring-1 focus:ring-admin-accent/30"
              />
              <p className="text-xs text-amber-500 mt-1.5">
                Higher values increase API usage proportionally. State may be slightly stale between concurrent pipelines within the same round.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
