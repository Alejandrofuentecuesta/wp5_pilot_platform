"use client"

import { useEffect, useState } from "react"
import type { ExperimentalConfig, TreatmentGroup, SeedArticle, FeatureMeta, PoolAgent, HumanizeRules } from "../../../lib/admin-types"
import { createExperimental3x3Preset } from "../../../lib/treatment-presets"
import { createSeedFromTemplate, getNewsTemplateById, NEWS_TEMPLATE_OPTIONS, type NewsTemplateId } from "../../../lib/news-story-options"
import { DEFAULT_AGENT_POOL, autoSelectAgents, getAgentPoolPreset, parseTargetsFromCriteria } from "../../../lib/agent-pool-presets"

interface StepTreatmentsProps {
  config: ExperimentalConfig
  onChange: (config: ExperimentalConfig) => void
  availableFeatures: FeatureMeta[]
  agentMode: "prompt" | "pool"
  humanizeEnabled?: boolean
  humanizePerAgent?: Record<string, HumanizeRules>
  onHumanizePerAgentChange?: (perAgent: Record<string, HumanizeRules>) => void
}

const inputClass = "w-full px-3 py-2 border border-admin-border rounded-lg text-sm bg-admin-surface text-admin-text focus:outline-none focus:border-admin-accent focus:ring-1 focus:ring-admin-accent/30"
const DEFAULT_GROUP_FEATURES = ["news_article", "gate_until_user_post"]

function detectGlobalTemplateId(groups: Record<string, TreatmentGroup>): string {
  const templateIds = Object.values(groups)
    .filter((group) => (group.features ?? DEFAULT_GROUP_FEATURES).includes("news_article"))
    .map((group) => group.seed?.template_id)
    .filter((templateId): templateId is string => Boolean(templateId))

  if (templateIds.length === 0) return ""
  const [first] = templateIds
  return templateIds.every((templateId) => templateId === first) ? first : ""
}

function SeedEditor({
  seed,
  globalTemplateId,
  onChange,
  onSelectTemplate,
}: {
  seed: SeedArticle
  globalTemplateId: string
  onChange: (seed: SeedArticle) => void
  onSelectTemplate: (templateId: string) => void
}) {
  const globalLabel = NEWS_TEMPLATE_OPTIONS.find((option) => option.id === globalTemplateId)?.label ?? "none"

  return (
    <div className="space-y-3 pl-4 border-l-2 border-admin-border mt-3">
      <p className="text-xs font-medium text-admin-muted uppercase tracking-wider">Seed Article</p>
      <div>
        <label className="block text-xs font-medium text-admin-muted mb-1">Seed preset (per treatment)</label>
        <select
          value={seed.template_id || ""}
          onChange={(e) => onSelectTemplate(e.target.value)}
          className={inputClass}
        >
          <option value="">Use global preset ({globalLabel})</option>
          {NEWS_TEMPLATE_OPTIONS.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="block text-xs font-medium text-admin-muted mb-1">Headline</label>
        <input
          type="text"
          value={seed.headline}
          onChange={(e) => onChange({ ...seed, headline: e.target.value })}
          className={inputClass}
        />
      </div>
      <div>
        <label className="block text-xs font-medium text-admin-muted mb-1">Source</label>
        <input
          type="text"
          value={seed.source}
          onChange={(e) => onChange({ ...seed, source: e.target.value })}
          placeholder="e.g. Reuters"
          className={inputClass}
        />
      </div>
      <div>
        <label className="block text-xs font-medium text-admin-muted mb-1">Body</label>
        <textarea
          value={seed.body}
          onChange={(e) => onChange({ ...seed, body: e.target.value })}
          rows={3}
          className={`${inputClass} resize-vertical`}
        />
      </div>
      <div>
        <label className="block text-xs font-medium text-admin-muted mb-1">Agent summary</label>
        <textarea
          value={seed.agent_summary || ""}
          onChange={(e) => onChange({ ...seed, agent_summary: e.target.value })}
          rows={2}
          placeholder="Short summary injected into agent context when 'Agents see article summary' is enabled. You can also paste the full body here if token budget allows."
          className={`${inputClass} resize-vertical`}
        />
        <p className="text-xs text-admin-faint mt-1">Keep it to 2–4 sentences to avoid inflating prompts. If left empty, agents will not receive article content even if the toggle is on.</p>
      </div>
    </div>
  )
}

function FeatureCheckboxes({
  features,
  onChange,
  availableFeatures,
}: {
  features: string[]
  onChange: (features: string[]) => void
  availableFeatures: FeatureMeta[]
}) {
  const toggle = (id: string) => {
    if (features.includes(id)) {
      onChange(features.filter((f) => f !== id))
    } else {
      onChange([...features, id])
    }
  }

  return (
    <div className="space-y-2">
      <label className="block text-xs font-medium text-admin-muted mb-1">Features</label>
      {availableFeatures.map((feat) => (
        <label key={feat.id} className="flex items-start gap-2 cursor-pointer group">
          <input
            type="checkbox"
            checked={features.includes(feat.id)}
            onChange={() => toggle(feat.id)}
            className="mt-0.5 rounded border-admin-border text-admin-accent focus:ring-admin-accent/30"
          />
          <div>
            <span className="text-sm font-medium text-admin-text group-hover:opacity-80">{feat.label}</span>
            <p className="text-xs text-admin-faint">{feat.description}</p>
          </div>
        </label>
      ))}
    </div>
  )
}

const INCIVILITY_BADGE: Record<string, { label: string; cls: string }> = {
  civil:    { label: "Civil",    cls: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300" },
  moderate: { label: "Moderate", cls: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300" },
  uncivil:  { label: "Uncivil",  cls: "bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300" },
}

const IDEOLOGY_BADGE: Record<string, { label: string; cls: string }> = {
  left:   { label: "Left",   cls: "bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300" },
  center: { label: "Center", cls: "bg-stone-100 text-stone-700 dark:bg-stone-700/40 dark:text-stone-200" },
  right:  { label: "Right",  cls: "bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300" },
}

const HUMANIZE_FIELDS: { key: keyof HumanizeRules; label: string; desc: string; def: number }[] = [
  { key: "strip_hashtags",       label: "Strip hashtags",           desc: "Removes #hashtag tokens",                        def: 100 },
  { key: "strip_inverted_punct", label: "Remove ¿ / ¡",             desc: "Drops Spanish inverted punctuation",              def: 100 },
  { key: "word_subs",            label: "Word contractions",         desc: "que→q, xq→porque, tb→también, pa→para, x→por…",  def: 80  },
  { key: "drop_accents",         label: "Drop accents",              desc: "Per-message chance to strip all accents",         def: 40  },
  { key: "comma_spacing",        label: "Remove space after comma",  desc: "Per-comma chance: hola,como vs hola, como",      def: 50  },
]

const DEFAULT_HUMANIZE_RULES: HumanizeRules = {
  strip_hashtags: 100,
  strip_inverted_punct: 100,
  word_subs: 80,
  drop_accents: 40,
  comma_spacing: 50,
  max_emoji: 1,
}

function HumanizeRulesEditor({ rules, onChange }: { rules: HumanizeRules; onChange: (r: HumanizeRules) => void }) {
  const set = (key: keyof HumanizeRules, value: number) => onChange({ ...rules, [key]: value })
  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-3 mt-2">
      {HUMANIZE_FIELDS.map(({ key, label, desc, def }) => {
        const val = rules[key] ?? def
        return (
          <div key={key}>
            <div className="flex items-center justify-between mb-1">
              <p className="text-xs font-medium text-admin-text">{label}</p>
              <div className="flex items-center gap-1">
                <input
                  type="number" min={0} max={100} value={val}
                  onChange={(e) => set(key, Math.min(100, Math.max(0, parseInt(e.target.value) || 0)))}
                  className="w-12 px-1.5 py-0.5 border border-admin-border rounded text-xs bg-admin-surface text-admin-text text-right focus:outline-none focus:border-admin-accent"
                />
                <span className="text-xs text-admin-faint">%</span>
              </div>
            </div>
            <input
              type="range" min={0} max={100} value={val}
              onChange={(e) => set(key, parseInt(e.target.value))}
              className="w-full h-1.5 accent-admin-accent"
            />
            <p className="text-xs text-admin-faint mt-0.5">{desc}</p>
          </div>
        )
      })}
      <div>
        <div className="flex items-center justify-between mb-1">
          <p className="text-xs font-medium text-admin-text">Max emoji</p>
          <input
            type="number" min={-1} max={10} value={rules.max_emoji ?? 1}
            onChange={(e) => set("max_emoji", parseInt(e.target.value) ?? 1)}
            className="w-12 px-1.5 py-0.5 border border-admin-border rounded text-xs bg-admin-surface text-admin-text text-right focus:outline-none focus:border-admin-accent"
          />
        </div>
        <p className="text-xs text-admin-faint">-1 = unlimited · 0 = strip all</p>
      </div>
    </div>
  )
}

const DEFAULT_POOL_INCIVILITY: PoolAgent["incivility"] = "civil"

function makeNextPoolAgentId(pool: PoolAgent[]): string {
  let idx = pool.length + 1
  const existing = new Set(pool.map((agent) => agent.id))
  while (existing.has(`agent_${idx}`)) idx += 1
  return `agent_${idx}`
}

function AgentPoolEditor({
  pool,
  onChange,
  selectedTemplateId,
  humanizeEnabled,
  humanizePerAgent,
  onHumanizePerAgentChange,
}: {
  pool: PoolAgent[]
  onChange: (pool: PoolAgent[]) => void
  selectedTemplateId: string
  humanizeEnabled?: boolean
  humanizePerAgent?: Record<string, HumanizeRules>
  onHumanizePerAgentChange?: (perAgent: Record<string, HumanizeRules>) => void
}) {
  const addAgent = () => {
    const next: PoolAgent = {
      id: makeNextPoolAgentId(pool),
      name: `Agente ${pool.length + 1}`,
      incivility: DEFAULT_POOL_INCIVILITY,
      ideology: "center",
      persona: "",
    }
    onChange([...pool, next])
  }

  const updateAgent = (index: number, updates: Partial<PoolAgent>) => {
    onChange(pool.map((agent, i) => (i === index ? { ...agent, ...updates } : agent)))
  }

  const removeAgent = (index: number) => {
    onChange(pool.filter((_, i) => i !== index))
  }

  const loadDefaultPool = () => {
    onChange(selectedTemplateId ? getAgentPoolPreset(selectedTemplateId) : DEFAULT_AGENT_POOL.map((agent) => ({ ...agent })))
  }

  return (
    <div className="bg-admin-surface rounded-lg border border-admin-border p-5 space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-admin-muted uppercase tracking-wider">Agent Pool</h3>
          <p className="text-xs text-admin-faint mt-1">
            Define the fixed agents used by the experiment when the session runs in pool mode.
            The Director still follows the treatment&apos;s internal validity criteria; the pool only makes that behaviour more consistent.
            The participant&apos;s pre-session stance is used as an extra hint when selecting the final live agents.
            {selectedTemplateId ? " The selected news story has a matching topic pool." : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={loadDefaultPool}
            className="px-3 py-1.5 text-xs font-medium border border-admin-border rounded-lg text-admin-muted hover:border-admin-accent/50 hover:text-admin-text transition-colors"
          >
            {selectedTemplateId ? "Load story pool" : "Load default pool"}
          </button>
          <button
            type="button"
            onClick={addAgent}
            className="px-3 py-1.5 text-xs font-medium bg-admin-accent text-white rounded-lg hover:bg-admin-accent-hover transition-colors"
          >
            + Add agent
          </button>
        </div>
      </div>

      {pool.length === 0 && (
        <div className="rounded-lg border border-dashed border-admin-border p-4 text-sm text-admin-faint">
          No pool agents yet. Add a few agents, then assign them to each treatment below.
        </div>
      )}

      <div className="space-y-3">
        {pool.map((agent, index) => (
          <div key={agent.id} className="rounded-lg border border-admin-border p-4 space-y-3">
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1 grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-admin-muted mb-1">ID</label>
                  <input
                    type="text"
                    value={agent.id}
                    readOnly
                    className={`${inputClass} font-mono opacity-80`}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-admin-muted mb-1">Name</label>
                  <input
                    type="text"
                    value={agent.name}
                    onChange={(e) => updateAgent(index, { name: e.target.value })}
                    className={inputClass}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-admin-muted mb-1">Incivility</label>
                  <select
                    value={agent.incivility}
                    onChange={(e) => updateAgent(index, { incivility: e.target.value as PoolAgent["incivility"] })}
                    className={inputClass}
                  >
                    <option value="civil">Civil</option>
                    <option value="moderate">Moderate</option>
                    <option value="uncivil">Uncivil</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-admin-muted mb-1">Ideology</label>
                  <select
                    value={agent.ideology}
                    onChange={(e) => updateAgent(index, { ideology: e.target.value as PoolAgent["ideology"] })}
                    className={inputClass}
                  >
                    <option value="left">Left</option>
                    <option value="center">Center</option>
                    <option value="right">Right</option>
                  </select>
                </div>
              </div>
              <button
                type="button"
                onClick={() => removeAgent(index)}
                className="text-xs text-red-500 hover:text-red-700 font-medium transition-colors mt-6"
              >
                Remove
              </button>
            </div>
            <div>
              <label className="block text-xs font-medium text-admin-muted mb-1">Persona</label>
              <textarea
                value={agent.persona}
                onChange={(e) => updateAgent(index, { persona: e.target.value })}
                rows={3}
                className={`${inputClass} resize-vertical`}
                placeholder="Describe the agent's personality, background, and communication style..."
              />
            </div>
            {humanizeEnabled && onHumanizePerAgentChange && (() => {
              const perAgent = humanizePerAgent ?? {}
              const hasOverride = agent.name in perAgent
              const toggleOverride = () => {
                if (hasOverride) {
                  const { [agent.name]: _, ...rest } = perAgent
                  onHumanizePerAgentChange(rest)
                } else {
                  onHumanizePerAgentChange({ ...perAgent, [agent.name]: { ...DEFAULT_HUMANIZE_RULES } })
                }
              }
              return (
                <div className="border-t border-admin-border pt-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <p className="text-xs font-medium text-admin-muted">Humanizer</p>
                    <button
                      type="button"
                      onClick={toggleOverride}
                      className={`px-2.5 py-1 text-xs font-medium rounded-lg border transition-colors ${
                        hasOverride
                          ? "bg-admin-accent text-white border-admin-accent"
                          : "border-admin-border text-admin-muted hover:border-admin-accent/50"
                      }`}
                    >
                      {hasOverride ? "Override general" : "Use general"}
                    </button>
                  </div>
                  {hasOverride && (
                    <HumanizeRulesEditor
                      rules={perAgent[agent.name]}
                      onChange={(r) => onHumanizePerAgentChange({ ...perAgent, [agent.name]: r })}
                    />
                  )}
                </div>
              )
            })()}
          </div>
        ))}
      </div>
    </div>
  )
}

function PoolAgentSelector({
  pool,
  selectedIds,
  onChange,
  criteria,
}: {
  pool: PoolAgent[]
  selectedIds: string[]
  onChange: (ids: string[]) => void
  criteria: string
}) {
  const toggle = (id: string) => {
    if (selectedIds.includes(id)) {
      onChange(selectedIds.filter((i) => i !== id))
    } else {
      onChange([...selectedIds, id])
    }
  }

  const handleAutoSelect = () => {
    const targets = parseTargetsFromCriteria(criteria)
    const ids = autoSelectAgents(pool, targets.likeMinded, targets.incivility, 5)
    onChange(ids)
  }

  // Group by ideology
  const byIdeology: Record<string, PoolAgent[]> = {}
  for (const agent of pool) {
    const key = agent.ideology
    if (!byIdeology[key]) byIdeology[key] = []
    byIdeology[key].push(agent)
  }

  return (
    <div className="space-y-3 border-t border-admin-border pt-3">
      <div className="flex items-center justify-between">
        <label className="block text-xs font-medium text-admin-muted uppercase tracking-wider">
          Pool agents ({selectedIds.length} selected)
        </label>
        <button
          type="button"
          onClick={handleAutoSelect}
          className="text-xs font-medium border border-admin-accent/40 rounded-lg px-2.5 py-1 bg-admin-surface text-admin-accent hover:bg-admin-accent/10"
          title="Auto-select 5 agents based on treatment targets"
        >
          Auto-select
        </button>
      </div>
      {pool.length === 0 && (
        <div className="rounded-lg border border-dashed border-admin-border px-3 py-2 text-xs text-admin-faint">
          No agents have been added to the pool yet. Use the agent pool editor above to load or create agents, then assign them here.
          The backend will use the participant&apos;s survey answer to choose the final agents from this candidate pool.
        </div>
      )}
      {Object.entries(byIdeology).map(([ideology, agents]) => (
        <div key={ideology}>
          <p className="text-xs text-admin-faint mb-1 capitalize">{ideology}</p>
          <div className="flex flex-wrap gap-1.5">
            {agents.map((agent) => {
              const selected = selectedIds.includes(agent.id)
              const incivilBadge = INCIVILITY_BADGE[agent.incivility] ?? INCIVILITY_BADGE.civil
              const ideologyBadge = IDEOLOGY_BADGE[agent.ideology] ?? IDEOLOGY_BADGE.center
              return (
                <button
                  key={agent.id}
                  type="button"
                  onClick={() => toggle(agent.id)}
                  className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-xs transition-all ${
                    selected
                      ? "border-admin-accent bg-admin-accent/10 text-admin-text ring-1 ring-admin-accent/30"
                      : "border-admin-border text-admin-muted hover:border-admin-accent/40"
                  }`}
                  title={agent.persona}
                >
                  <span className="font-medium">{agent.name}</span>
                  <span className={`px-1 py-0.5 rounded text-[10px] leading-none ${ideologyBadge.cls}`}>
                    {ideologyBadge.label}
                  </span>
                  <span className={`px-1 py-0.5 rounded text-[10px] leading-none ${incivilBadge.cls}`}>
                    {incivilBadge.label}
                  </span>
                </button>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

function GroupCard({
  name,
  group,
  globalTemplateId,
  onChangeName,
  onChangeGroup,
  onSelectGroupTemplate,
  onRemove,
  availableFeatures,
  agentMode,
  agentPool,
}: {
  name: string
  group: TreatmentGroup
  globalTemplateId: string
  onChangeName: (name: string) => void
  onChangeGroup: (group: TreatmentGroup) => void
  onSelectGroupTemplate: (templateId: string) => void
  onRemove: () => void
  availableFeatures: FeatureMeta[]
  agentMode: "prompt" | "pool"
  agentPool: PoolAgent[]
}) {
  const features = group.features ?? DEFAULT_GROUP_FEATURES

  return (
    <div className="bg-admin-surface rounded-lg border border-admin-border p-5 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1">
          <label className="block text-xs font-medium text-admin-muted mb-1">Group name</label>
          <input
            type="text"
            value={name}
            onChange={(e) => onChangeName(e.target.value.replace(/[^a-z0-9_]/gi, "_").toLowerCase())}
            placeholder="e.g. not_incivil_mix"
            className={`${inputClass} font-mono`}
          />
        </div>
        <button
          onClick={onRemove}
          className="mt-5 text-xs text-red-500 hover:text-red-700 font-medium transition-colors"
        >
          Remove
        </button>
      </div>

      <FeatureCheckboxes
        features={features}
        onChange={(f) => onChangeGroup({ ...group, features: f })}
        availableFeatures={availableFeatures}
      />

      <div>
        <label className="block text-xs font-medium text-admin-muted mb-1">Internal validity criteria</label>
        <textarea
          value={group.internal_validity_criteria}
          onChange={(e) => onChangeGroup({ ...group, internal_validity_criteria: e.target.value })}
          rows={4}
          placeholder="Describe the internal validity criteria for this condition, ideally referencing the shared incivility framework if you defined one..."
          className={`${inputClass} resize-vertical`}
        />
      </div>

      {agentMode === "pool" && agentPool.length > 0 && (
        <PoolAgentSelector
          pool={agentPool}
          selectedIds={group.pool_agent_ids || []}
          onChange={(ids) => onChangeGroup({ ...group, pool_agent_ids: ids })}
          criteria={group.internal_validity_criteria}
        />
      )}

      {features.includes("news_article") && (
        <>
          <SeedEditor
            seed={group.seed || { type: "news_article", template_id: "", headline: "", source: "", body: "" }}
            globalTemplateId={globalTemplateId}
            onChange={(seed) => onChangeGroup({ ...group, seed })}
            onSelectTemplate={onSelectGroupTemplate}
          />
          <label className="flex items-center gap-2 cursor-pointer mt-2 pl-4">
            <input
              type="checkbox"
              checked={group.agents_see_article ?? false}
              onChange={(e) => onChangeGroup({ ...group, agents_see_article: e.target.checked })}
              className="rounded border-admin-border text-admin-accent focus:ring-admin-accent/30"
            />
            <span className="text-sm text-admin-text">Agents see article summary</span>
            <span className="text-xs text-admin-faint">— injects the headline and body into the agents&apos; chatroom context</span>
          </label>
        </>
      )}
    </div>
  )
}

export default function StepTreatments({ config, onChange, availableFeatures, agentMode, humanizeEnabled, humanizePerAgent, onHumanizePerAgentChange }: StepTreatmentsProps) {
  const [showBuilder, setShowBuilder] = useState(false)
  const [dimA, setDimA] = useState({ name: "", levels: ["", ""] })
  const [dimB, setDimB] = useState({ name: "", levels: ["", ""] })
  const [selectedNewsTemplate, setSelectedNewsTemplate] = useState("")

  useEffect(() => {
    const detectedTemplateId = detectGlobalTemplateId(config.groups)
    setSelectedNewsTemplate((current) => (current === detectedTemplateId ? current : detectedTemplateId))
  }, [config.groups])

  const groupEntries = Object.entries(config.groups)
  const agentPool = config.agent_pool || []

  const updateAgentPool = (pool: PoolAgent[]) => {
    const validIds = new Set(pool.map((agent) => agent.id))
    const groups: Record<string, TreatmentGroup> = {}
    for (const [name, group] of Object.entries(config.groups)) {
      groups[name] = {
        ...group,
        pool_agent_ids: (group.pool_agent_ids || []).filter((id) => validIds.has(id)),
      }
    }
    onChange({
      ...config,
      agent_pool: pool,
      groups,
    })
  }

  const applyPoolPreset = (
    baseConfig: ExperimentalConfig,
    templateId: NewsTemplateId
  ): ExperimentalConfig => {
    const pool = getAgentPoolPreset(templateId)
    const poolIds = pool.map((agent) => agent.id)
    const groups: Record<string, TreatmentGroup> = {}

    for (const [name, group] of Object.entries(baseConfig.groups)) {
      groups[name] = {
        ...group,
        pool_agent_ids: [...poolIds],
      }
    }

    return {
      ...baseConfig,
      agent_pool: pool,
      groups,
    }
  }

  const populateEmptySeedFields = (
    groups: Record<string, TreatmentGroup>,
    templateId: string
  ): Record<string, TreatmentGroup> => {
    const nextGroups: Record<string, TreatmentGroup> = {}
    for (const [groupName, group] of Object.entries(groups)) {
      const groupFeatures = group.features ?? DEFAULT_GROUP_FEATURES
      if (!groupFeatures.includes("news_article")) {
        nextGroups[groupName] = group
        continue
      }

      const activeTemplateId = group.seed?.template_id || templateId
      const template = getNewsTemplateById(activeTemplateId)
      if (!template) {
        nextGroups[groupName] = { ...group, features: groupFeatures }
        continue
      }

      const currentSeed = group.seed ?? { type: "news_article", headline: "", source: "", body: "" }
      nextGroups[groupName] = {
        ...group,
        features: groupFeatures,
        seed: {
          ...currentSeed,
          type: "news_article",
          template_id: currentSeed.template_id,
          headline: currentSeed.headline.trim() ? currentSeed.headline : template.article.headline,
          source: currentSeed.source.trim() ? currentSeed.source : template.article.source,
          body: currentSeed.body.trim() ? currentSeed.body : template.article.body,
        },
      }
    }
    return nextGroups
  }

  const applyTemplateToAllNewsGroups = (
    groups: Record<string, TreatmentGroup>,
    templateId: string
  ): Record<string, TreatmentGroup> => {
    const templateSeed = createSeedFromTemplate(templateId)
    if (!templateSeed) return groups

    const nextGroups: Record<string, TreatmentGroup> = {}
    for (const [groupName, group] of Object.entries(groups)) {
      const groupFeatures = group.features ?? DEFAULT_GROUP_FEATURES
      if (!groupFeatures.includes("news_article")) {
        nextGroups[groupName] = group
        continue
      }

      nextGroups[groupName] = {
        ...group,
        features: groupFeatures,
        seed: {
          ...templateSeed,
        },
      }
    }
    return nextGroups
  }

  const applyTemplateToCurrentGroups = (templateId: string) => {
    let nextConfig: ExperimentalConfig = {
      ...config,
      groups: applyTemplateToAllNewsGroups(config.groups, templateId),
    }

    if (agentMode === "pool" && templateId) {
      nextConfig = applyPoolPreset(nextConfig, templateId as NewsTemplateId)
    }

    onChange(nextConfig)
  }

  const addGroup = () => {
    const defaultPoolIds = agentMode === "pool" ? agentPool.map((agent) => agent.id) : []
    const newName = `group_${groupEntries.length + 1}`
    const nextGroups: Record<string, TreatmentGroup> = {
      ...config.groups,
      [newName]: {
        features: [...DEFAULT_GROUP_FEATURES],
        internal_validity_criteria: "",
        agents_see_article: true,
        pool_agent_ids: defaultPoolIds,
      },
    }

    onChange({
      ...config,
      groups: selectedNewsTemplate
        ? applyTemplateToAllNewsGroups(nextGroups, selectedNewsTemplate)
        : populateEmptySeedFields(nextGroups, selectedNewsTemplate),
    })
  }

  const removeGroup = (name: string) => {
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { [name]: _, ...rest } = config.groups
    onChange({ ...config, groups: rest })
  }

  const renameGroup = (oldName: string, newName: string) => {
    if (newName === oldName) return
    const entries = Object.entries(config.groups)
    const newGroups: Record<string, TreatmentGroup> = {}
    for (const [k, v] of entries) {
      newGroups[k === oldName ? newName : k] = v
    }
    onChange({ ...config, groups: newGroups })
  }

  const updateGroup = (name: string, group: TreatmentGroup) => {
    onChange({
      ...config,
      groups: { ...config.groups, [name]: group },
    })
  }

  const applyTemplateToGroup = (groupName: string, templateId: string) => {
    const group = config.groups[groupName]
    if (!group) return

    if (!templateId) {
      const restSeed = { ...(group.seed || { type: "news_article", headline: "", source: "", body: "" }) }
      delete restSeed.template_id
      updateGroup(groupName, { ...group, seed: restSeed })
      return
    }

    const seed = createSeedFromTemplate(templateId)
    if (!seed) return
    updateGroup(groupName, { ...group, seed })
  }

  const generate2x2 = () => {
    const defaultPoolIds = agentMode === "pool" ? agentPool.map((agent) => agent.id) : []
    const groups: Record<string, TreatmentGroup> = {}
    for (const a of dimA.levels) {
      for (const b of dimB.levels) {
        const slug = `${a}_${b}`.toLowerCase().replace(/[^a-z0-9_]/g, "_")
        groups[slug] = {
          features: [...DEFAULT_GROUP_FEATURES],
          internal_validity_criteria: "",
          agents_see_article: true,
          pool_agent_ids: defaultPoolIds,
        }
      }
    }
    onChange({ ...config, groups: populateEmptySeedFields(groups, selectedNewsTemplate) })
    setShowBuilder(false)
  }

  const load3x3Preset = () => {
    const preset = createExperimental3x3Preset(selectedNewsTemplate || undefined)
    let nextConfig: ExperimentalConfig = {
      ...preset,
      groups: selectedNewsTemplate
        ? applyTemplateToAllNewsGroups(preset.groups, selectedNewsTemplate)
        : populateEmptySeedFields(preset.groups, selectedNewsTemplate),
    }

    if (agentMode === "pool" && selectedNewsTemplate) {
      nextConfig = applyPoolPreset(nextConfig, selectedNewsTemplate as NewsTemplateId)
    }

    onChange(nextConfig)
    setShowBuilder(false)
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-admin-text">Treatment Groups</h2>
        <p className="text-sm text-admin-muted mt-1">
          Define the shared chatroom setup, optional incivility framework, and treatment conditions for each group.
          In agent mode, the pool sets who can speak, while the Director still steers the conversation toward the internal validity criteria.
        </p>
      </div>

      <div className="bg-admin-surface rounded-lg border border-admin-border p-5 space-y-4">
        <div>
          <label className="block text-sm font-medium text-admin-text mb-1">News story preset</label>
          <select
            value={selectedNewsTemplate}
            onChange={(e) => {
              const selectedId = e.target.value
              setSelectedNewsTemplate(selectedId)
              if (selectedId) {
                applyTemplateToCurrentGroups(selectedId)
              }
            }}
            className={inputClass}
          >
            <option value="">Select a story (optional)</option>
            {NEWS_TEMPLATE_OPTIONS.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
          <p className="text-xs text-admin-faint mt-1">
            Applies to all treatments with <code>news_article</code> and replaces the current article seed in those groups. You can edit every treatment manually afterwards.
            {agentMode === "pool" ? " In agent mode, selecting a story also loads its matching topic pool preset." : ""}
          </p>
        </div>

        <div>
          <label className="block text-sm font-medium text-admin-text mb-1">Chatroom context</label>
          <textarea
            value={config.chatroom_context}
            onChange={(e) => onChange({ ...config, chatroom_context: e.target.value })}
            rows={3}
            placeholder="e.g. This is a Spanish-language chatroom on Telegram, based in Spain."
            className={`${inputClass} resize-vertical`}
          />
          <p className="text-xs text-admin-faint mt-1">The topic and setting of the chatroom. Shared across all treatment groups.</p>
        </div>
        <div>
          <label className="block text-sm font-medium text-admin-text mb-1">Incivility framework</label>
          <textarea
            value={config.incivility_framework}
            onChange={(e) => onChange({ ...config, incivility_framework: e.target.value })}
            rows={6}
            placeholder="Optional shared definition of incivility, its levels, and the forms that are allowed or disallowed across this experiment."
            className={`${inputClass} resize-vertical`}
          />
          <p className="text-xs text-admin-faint mt-1">
            Optional shared taxonomy for incivility. Use this for the long definition, levels, and allowed forms, then keep each treatment focused on the target level or pattern.
          </p>
        </div>
        <div>
          <label className="block text-sm font-medium text-admin-text mb-1">Ecological validity criteria</label>
          <textarea
            value={config.ecological_validity_criteria}
            onChange={(e) => onChange({ ...config, ecological_validity_criteria: e.target.value })}
            rows={4}
            placeholder="e.g. The chatroom should resemble an informal Reddit thread: short messages, casual tone, a mix of agreement and disagreement, with frequent use of likes and occasional humour."
            className={`${inputClass} resize-vertical`}
          />
          <p className="text-xs text-admin-faint mt-1">What &ldquo;realistic&rdquo; means for this chatroom. The Director uses this to maintain natural conversational flow. Shared across all treatment groups.</p>
        </div>
      </div>

      {agentMode === "pool" && (
        <AgentPoolEditor
          pool={agentPool}
          onChange={updateAgentPool}
          selectedTemplateId={selectedNewsTemplate}
          humanizeEnabled={humanizeEnabled}
          humanizePerAgent={humanizePerAgent}
          onHumanizePerAgentChange={onHumanizePerAgentChange}
        />
      )}

      {/* 2x2 builder */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => setShowBuilder(!showBuilder)}
          className="text-xs font-medium text-admin-accent hover:text-admin-accent-hover underline underline-offset-2 transition-colors"
        >
          {showBuilder ? "Hide 2×2 builder" : "Generate 2×2 design"}
        </button>
        <button
          onClick={load3x3Preset}
          className="text-xs font-medium text-admin-accent hover:text-admin-accent-hover underline underline-offset-2 transition-colors"
        >
          Load 3x3 preset
        </button>
        <button
          onClick={addGroup}
          className="text-xs font-medium text-admin-pastel-green-text hover:opacity-80 underline underline-offset-2 transition-colors"
        >
          + Add group manually
        </button>
      </div>

      {showBuilder && (
        <div className="bg-admin-accent-soft rounded-lg border border-admin-accent-muted p-5 space-y-3">
          <p className="text-xs font-medium text-admin-accent">
            Generate a 2x2 factorial design. This will replace all existing groups.
          </p>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-admin-muted mb-1">Dimension A</label>
              <input
                type="text"
                value={dimA.name}
                onChange={(e) => setDimA({ ...dimA, name: e.target.value })}
                placeholder="e.g. civility"
                className={`${inputClass} mb-2`}
              />
              <div className="flex gap-2">
                {dimA.levels.map((level, i) => (
                  <input
                    key={i}
                    type="text"
                    value={level}
                    onChange={(e) => {
                      const levels = [...dimA.levels]
                      levels[i] = e.target.value
                      setDimA({ ...dimA, levels })
                    }}
                    placeholder={`Level ${i + 1}`}
                    className="flex-1 px-2 py-1 border border-admin-border rounded text-xs bg-admin-surface text-admin-text"
                  />
                ))}
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-admin-muted mb-1">Dimension B</label>
              <input
                type="text"
                value={dimB.name}
                onChange={(e) => setDimB({ ...dimB, name: e.target.value })}
                placeholder="e.g. stance"
                className={`${inputClass} mb-2`}
              />
              <div className="flex gap-2">
                {dimB.levels.map((level, i) => (
                  <input
                    key={i}
                    type="text"
                    value={level}
                    onChange={(e) => {
                      const levels = [...dimB.levels]
                      levels[i] = e.target.value
                      setDimB({ ...dimB, levels })
                    }}
                    placeholder={`Level ${i + 1}`}
                    className="flex-1 px-2 py-1 border border-admin-border rounded text-xs bg-admin-surface text-admin-text"
                  />
                ))}
              </div>
            </div>
          </div>
          <button
            onClick={generate2x2}
            className="px-4 py-1.5 text-xs font-medium bg-admin-accent text-white rounded-lg hover:bg-admin-accent-hover transition-colors"
          >
            Generate 4 groups
          </button>
        </div>
      )}

      {/* Group cards */}
      <div className="space-y-4">
        {groupEntries.map(([name, group], index) => (
          <GroupCard
            key={index}
            name={name}
            group={group}
            globalTemplateId={selectedNewsTemplate}
            onChangeName={(newName) => renameGroup(name, newName)}
            onChangeGroup={(g) => updateGroup(name, g)}
            onSelectGroupTemplate={(templateId) => applyTemplateToGroup(name, templateId)}
            onRemove={() => removeGroup(name)}
            availableFeatures={availableFeatures}
            agentMode={agentMode}
            agentPool={agentPool}
          />
        ))}
      </div>

      {groupEntries.length === 0 && (
        <div className="text-center py-8 text-admin-faint text-sm">
          No treatment groups defined. Add one manually, use the 2x2 builder, or load the 3x3 preset.
        </div>
      )}
    </div>
  )
}
