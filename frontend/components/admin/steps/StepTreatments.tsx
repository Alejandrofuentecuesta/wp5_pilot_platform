"use client"

import { useState } from "react"
import type { ExperimentalConfig, TreatmentGroup, SeedArticle, FeatureMeta } from "../../../lib/admin-types"
import { createExperimental3x3Preset } from "../../../lib/treatment-presets"
import { createSeedFromTemplate, getNewsTemplateById, NEWS_TEMPLATE_OPTIONS } from "../../../lib/news-story-options"

interface StepTreatmentsProps {
  config: ExperimentalConfig
  onChange: (config: ExperimentalConfig) => void
  availableFeatures: FeatureMeta[]
}

const inputClass = "w-full px-3 py-2 border border-admin-border rounded-lg text-sm bg-admin-surface text-admin-text focus:outline-none focus:border-admin-accent focus:ring-1 focus:ring-admin-accent/30"
const DEFAULT_GROUP_FEATURES = ["news_article", "gate_until_user_post"]

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

function GroupCard({
  name,
  group,
  globalTemplateId,
  onChangeName,
  onChangeGroup,
  onSelectGroupTemplate,
  onRemove,
  availableFeatures,
}: {
  name: string
  group: TreatmentGroup
  globalTemplateId: string
  onChangeName: (name: string) => void
  onChangeGroup: (group: TreatmentGroup) => void
  onSelectGroupTemplate: (templateId: string) => void
  onRemove: () => void
  availableFeatures: FeatureMeta[]
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
            placeholder="e.g. uncivil_support"
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

      {features.includes("news_article") && (
        <SeedEditor
          seed={group.seed || { type: "news_article", template_id: "", headline: "", source: "", body: "" }}
          globalTemplateId={globalTemplateId}
          onChange={(seed) => onChangeGroup({ ...group, seed })}
          onSelectTemplate={onSelectGroupTemplate}
        />
      )}
    </div>
  )
}

export default function StepTreatments({ config, onChange, availableFeatures }: StepTreatmentsProps) {
  const [showBuilder, setShowBuilder] = useState(false)
  const [dimA, setDimA] = useState({ name: "", levels: ["", ""] })
  const [dimB, setDimB] = useState({ name: "", levels: ["", ""] })
  const [selectedNewsTemplate, setSelectedNewsTemplate] = useState("")

  const groupEntries = Object.entries(config.groups)

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

  const applyTemplateToCurrentGroups = (templateId: string) => {
    onChange({
      ...config,
      groups: populateEmptySeedFields(config.groups, templateId),
    })
  }

  const addGroup = () => {
    const newName = `group_${groupEntries.length + 1}`
    const nextGroups: Record<string, TreatmentGroup> = {
      ...config.groups,
      [newName]: { features: [...DEFAULT_GROUP_FEATURES], internal_validity_criteria: "" },
    }

    onChange({
      ...config,
      groups: populateEmptySeedFields(nextGroups, selectedNewsTemplate),
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
    const groups: Record<string, TreatmentGroup> = {}
    for (const a of dimA.levels) {
      for (const b of dimB.levels) {
        const slug = `${a}_${b}`.toLowerCase().replace(/[^a-z0-9_]/g, "_")
        groups[slug] = {
          features: [...DEFAULT_GROUP_FEATURES],
          internal_validity_criteria: "",
        }
      }
    }
    onChange({ ...config, groups: populateEmptySeedFields(groups, selectedNewsTemplate) })
    setShowBuilder(false)
  }

  const load3x3Preset = () => {
    const preset = createExperimental3x3Preset()
    onChange({
      ...preset,
      groups: populateEmptySeedFields(preset.groups, selectedNewsTemplate),
    })
    setShowBuilder(false)
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-admin-text">Treatment Groups</h2>
        <p className="text-sm text-admin-muted mt-1">
          Define the shared chatroom setup, optional incivility framework, and treatment conditions for each group.
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
            Applies to all treatments with <code>news_article</code> and only fills empty fields. You can edit every treatment manually afterwards.
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
