"use client"

import { useEffect, useState } from "react"
import type { SimulationConfig } from "../../../lib/admin-types"
import { normalizeAgentNames } from "../../../lib/agent-name-options"

interface StepSessionProps {
  config: SimulationConfig
  onChange: (updates: Partial<SimulationConfig>) => void
  touched: boolean
}

const inputClass = "w-full px-3 py-2 border border-admin-border rounded-lg text-sm bg-admin-surface text-admin-text focus:outline-none focus:border-admin-accent focus:ring-1 focus:ring-admin-accent/30"

export default function StepSession({ config, onChange, touched }: StepSessionProps) {
  const [showPersonas, setShowPersonas] = useState(false)

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

  const agentNameErrors = config.agent_names.map((name, i) => {
    if (!name.trim()) return "Required"
    if (config.agent_names.some((other, j) => j !== i && other.trim() === name.trim())) return "Duplicate"
    return null
  })

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-admin-text">Session & Agents</h2>
        <p className="text-sm text-admin-muted mt-1">
          Configure session timing, agent count, and message pacing.
        </p>
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
                <button
                  type="button"
                  onClick={() => setShowPersonas((prev) => !prev)}
                  className="text-xs font-medium border border-admin-border rounded-lg px-2.5 py-1 bg-admin-surface text-admin-muted hover:text-admin-text"
                >
                  {showPersonas ? "Hide" : "Add"}
                </button>
              </div>
              <p className="text-xs text-admin-faint mb-3">
                Optional. Enable this section only if you want to define custom personalities for each agent.
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
      </div>
    </div>
  )
}

