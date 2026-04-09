"use client"

import { useState, useEffect, useRef } from "react"
import type { SimulationConfig, ProviderParamsMeta, TestLLMResult } from "../../../lib/admin-types"
import { testLlm, fetchPromptDefaults } from "../../../lib/admin-api"

export type LLMTestResults = Record<Role, boolean>

interface StepLLMProps {
  config: SimulationConfig
  onChange: (updates: Partial<SimulationConfig>) => void
  llmProviders: string[]
  providerModels: Record<string, string[]>
  providerParams: Record<string, ProviderParamsMeta>
  adminKey: string
  onTestResult?: (role: Role, ok: boolean) => void
}

type Role = "director" | "performer" | "moderator" | "classifier"

const ROLE_DESCRIPTIONS: Record<Role, string> = {
  director: "Decides which agent acts, selects the action type, and provides structured instructions to the Performer.",
  performer: "Generates the actual chatroom message based on the Director's instructions.",
  moderator: "Extracts clean message content from the Performer's raw output. A fast, cheap model is ideal.",
  classifier: "Classifies each final agent message for incivility and like-mindedness with the participant's inferred stance.",
}

const ROLE_PROMPT_KEY: Record<Role, keyof SimulationConfig> = {
  director: "director_action_prompt_template",
  performer: "performer_prompt_template",
  moderator: "moderator_prompt_template",
  classifier: "classifier_prompt_template",
}

const inputClass = "w-full px-3 py-2 border border-admin-border rounded-lg text-sm bg-admin-surface text-admin-text focus:outline-none focus:border-admin-accent focus:ring-1 focus:ring-admin-accent/30"

function LLMRoleConfig({
  role,
  config,
  onChange,
  expanded,
  onToggle,
  llmProviders,
  providerModels,
  providerParams,
  adminKey,
  onTestResult,
  promptDefault,
  promptKey,
}: {
  role: Role
  config: SimulationConfig
  onChange: (updates: Partial<SimulationConfig>) => void
  expanded: boolean
  onToggle: () => void
  llmProviders: string[]
  providerModels: Record<string, string[]>
  providerParams: Record<string, ProviderParamsMeta>
  adminKey: string
  onTestResult?: (role: Role, ok: boolean) => void
  promptDefault: string
  promptKey: string
}) {
  const prefix = role
  const provider = config[`${prefix}_llm_provider` as keyof SimulationConfig] as string
  const model = config[`${prefix}_llm_model` as keyof SimulationConfig] as string
  const temperature = config[`${prefix}_temperature` as keyof SimulationConfig] as number
  const topP = config[`${prefix}_top_p` as keyof SimulationConfig] as number
  const maxTokens = config[`${prefix}_max_tokens` as keyof SimulationConfig] as number

  const suggestedModels = providerModels[provider] ?? []
  const isCustomModel = suggestedModels.length > 0 && !suggestedModels.includes(model)
  const [showCustomInput, setShowCustomInput] = useState(isCustomModel)

  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<TestLLMResult | null>(null)
  const [showPrompt, setShowPrompt] = useState(false)

  // Clear test result whenever provider or model changes (including via "Copy Director" button)
  const prevProviderRef = useRef(provider)
  const prevModelRef = useRef(model)
  useEffect(() => {
    if (prevProviderRef.current !== provider || prevModelRef.current !== model) {
      setTestResult(null)
      onTestResult?.(role, false)
    }
    prevProviderRef.current = provider
    prevModelRef.current = model
  }, [provider, model, role, onTestResult])

  const paramsMeta = providerParams[provider]
  const hasMutex = paramsMeta?.mutual_exclusion?.includes("temperature") &&
    paramsMeta?.mutual_exclusion?.includes("top_p")
  const bothSet = temperature != null && temperature > 0 && topP != null && topP > 0

  const set = (field: string, value: string | number) => {
    onChange({ [`${prefix}_${field}`]: value } as Partial<SimulationConfig>)
  }

  const handleProviderChange = (newProvider: string) => {
    set("llm_provider", newProvider)
    const models = providerModels[newProvider] ?? []
    if (models.length > 0) {
      set("llm_model", models[0])
      setShowCustomInput(false)
    }
    setTestResult(null)
    onTestResult?.(role, false)
  }

  const handleModelSelect = (value: string) => {
    if (value === "__custom__") {
      setShowCustomInput(true)
      set("llm_model", "")
    } else {
      setShowCustomInput(false)
      set("llm_model", value)
    }
    setTestResult(null)
    onTestResult?.(role, false)
  }

  const handleTest = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const result = await testLlm(adminKey, {
        provider,
        model,
        temperature: temperature || undefined,
        top_p: topP || undefined,
        max_tokens: maxTokens,
        bsc_model_version: provider === "bsc" ? (config.bsc_model_version ?? "v1") : undefined,
      })
      setTestResult(result)
      onTestResult?.(role, result.ok)
    } catch (e) {
      const failResult = {
        ok: false,
        call_params: { provider, model, temperature, top_p: topP, max_tokens: maxTokens },
        prompt: "",
        error: e instanceof Error ? e.message : "Request failed",
        warnings: [],
      }
      setTestResult(failResult)
      onTestResult?.(role, false)
    }
    setTesting(false)
  }

  return (
    <div className="bg-admin-surface rounded-lg border border-admin-border overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-5 py-3 hover:bg-admin-raised transition-colors"
      >
        <div className="text-left">
          <span className="text-sm font-semibold text-admin-text capitalize">{role}</span>
          <span className="text-xs text-admin-faint ml-2">
            {provider} / {model}
          </span>
        </div>
        <span className="text-admin-faint text-sm">{expanded ? "\u25B2" : "\u25BC"}</span>
      </button>

      {expanded && (
        <div className="px-5 pb-4 border-t border-admin-border pt-3 space-y-3">
          <p className="text-xs text-admin-muted">{ROLE_DESCRIPTIONS[role]}</p>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-admin-muted mb-1">Provider</label>
              <select
                value={provider}
                onChange={(e) => handleProviderChange(e.target.value)}
                className={inputClass}
              >
                {llmProviders.map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-admin-muted mb-1">Model</label>
              {suggestedModels.length > 0 ? (
                <>
                  <select
                    value={showCustomInput ? "__custom__" : model}
                    onChange={(e) => handleModelSelect(e.target.value)}
                    className={inputClass}
                  >
                    {suggestedModels.map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                    <option value="__custom__">Custom...</option>
                  </select>
                  {showCustomInput && (
                    <input
                      type="text"
                      value={model}
                      onChange={(e) => set("llm_model", e.target.value)}
                      placeholder="Enter model identifier"
                      className={`${inputClass} mt-2`}
                    />
                  )}
                </>
              ) : (
                <input
                  type="text"
                  value={model}
                  onChange={(e) => set("llm_model", e.target.value)}
                  placeholder="Enter model identifier"
                  className={inputClass}
                />
              )}
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="block text-xs font-medium text-admin-muted mb-1">
                Temperature <span className="text-admin-faint">(0–2)</span>
              </label>
              <input
                type="number"
                min={0}
                max={2}
                step={0.1}
                value={temperature}
                onChange={(e) => set("temperature", parseFloat(e.target.value) || 0)}
                className={inputClass}
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-admin-muted mb-1">
                Top-p <span className="text-admin-faint">(0–1)</span>
              </label>
              <input
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={topP}
                onChange={(e) => set("top_p", parseFloat(e.target.value) || 0)}
                className={inputClass}
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-admin-muted mb-1">Max tokens</label>
              <input
                type="number"
                min={1}
                value={maxTokens}
                onChange={(e) => set("max_tokens", Math.max(1, parseInt(e.target.value) || 1))}
                className={inputClass}
              />
            </div>
          </div>

          {/* Mutual-exclusion warning */}
          {hasMutex && bothSet && (
            <p className="text-xs text-amber-500">
              {provider} does not support both temperature and top_p — top_p will be ignored (temperature takes priority).
            </p>
          )}

          {/* Test LLM button */}
          <div className="pt-1">
            <button
              onClick={handleTest}
              disabled={testing || !model}
              className="px-3 py-1.5 text-xs font-medium rounded-md border border-admin-border text-admin-text hover:bg-admin-raised disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {testing ? "Testing..." : "Test LLM"}
            </button>
          </div>

          {/* Test result */}
          {testResult && (
            <div className={`rounded-lg border p-3 text-xs space-y-2 ${
              testResult.ok
                ? "border-green-600/30 bg-green-950/20"
                : "border-red-600/30 bg-red-950/20"
            }`}>
              {testResult.warnings.map((w, i) => (
                <p key={i} className="text-amber-500">{w}</p>
              ))}

              <div className="space-y-1 text-admin-muted">
                <p className="font-medium text-admin-text">
                  {testResult.ok ? "Success" : "Failed"}
                </p>
                <p>
                  <span className="text-admin-faint">Call: </span>
                  {String(testResult.call_params.provider)}/{String(testResult.call_params.model)}
                  {testResult.call_params.temperature != null && ` temp=${testResult.call_params.temperature}`}
                  {testResult.call_params.top_p != null && ` top_p=${testResult.call_params.top_p}`}
                  {` max_tokens=${testResult.call_params.max_tokens}`}
                </p>
                {testResult.prompt && (
                  <p>
                    <span className="text-admin-faint">Prompt: </span>
                    <span className="italic">&quot;{testResult.prompt}&quot;</span>
                  </p>
                )}
                {testResult.response && (
                  <p>
                    <span className="text-admin-faint">Response: </span>
                    <span className="text-admin-text">&quot;{testResult.response}&quot;</span>
                  </p>
                )}
                {testResult.error && (
                  <p className="text-red-400">
                    <span className="text-admin-faint">Error: </span>
                    {testResult.error}
                  </p>
                )}
              </div>
            </div>
          )}

          {/* Prompt Template */}
          <div className="pt-2 border-t border-admin-border">
            <button
              onClick={() => setShowPrompt(!showPrompt)}
              className="text-xs font-medium text-admin-accent hover:text-admin-accent-hover transition-colors"
            >
              {showPrompt ? "▲ Hide prompt template" : "▼ Edit prompt template"}
            </button>
            {showPrompt && (
              <div className="mt-2 space-y-2">
                <textarea
                  value={(config[promptKey as keyof SimulationConfig] as string) ?? ""}
                  onChange={(e) => onChange({ [promptKey]: e.target.value } as Partial<SimulationConfig>)}
                  rows={12}
                  className={`${inputClass} font-mono text-xs resize-y`}
                  placeholder={promptDefault || "Using default prompt from server..."}
                />
                <button
                  onClick={() => onChange({ [promptKey]: "" } as Partial<SimulationConfig>)}
                  className="text-xs text-admin-faint hover:text-admin-text transition-colors"
                >
                  Reset to default
                </button>
                {!(config[promptKey as keyof SimulationConfig] as string) && (
                  <p className="text-xs text-admin-faint italic">Using server default. Edit above to override.</p>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default function StepLLM({ config, onChange, llmProviders, providerModels, providerParams, adminKey, onTestResult }: StepLLMProps) {
  const [expanded, setExpanded] = useState<Role | null>("director")
  const [promptDefaults, setPromptDefaults] = useState<Record<string, string>>({})
  useEffect(() => {
    fetchPromptDefaults(adminKey).then(setPromptDefaults).catch(() => {})
  }, [adminKey])

  const copyDirectorToPerformer = () => {
    onChange({
      performer_llm_provider: config.director_llm_provider,
      performer_llm_model: config.director_llm_model,
      performer_temperature: config.director_temperature,
      performer_top_p: config.director_top_p,
      performer_max_tokens: config.director_max_tokens,
    })
  }

  const copyModeratorToClassifier = () => {
    onChange({
      classifier_llm_provider: config.moderator_llm_provider,
      classifier_llm_model: config.moderator_llm_model,
      classifier_temperature: config.moderator_temperature,
      classifier_top_p: config.moderator_top_p,
      classifier_max_tokens: config.moderator_max_tokens,
    })
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-admin-text">LLM Pipeline</h2>
        <p className="text-sm text-admin-muted mt-1">
          Configure the Director, Performer, Moderator, and Classifier models.
        </p>
      </div>

      <div className="space-y-3">
        {(["director", "performer", "moderator", "classifier"] as Role[]).map((role) => (
          <LLMRoleConfig
            key={role}
            role={role}
            config={config}
            onChange={onChange}
            expanded={expanded === role}
            onToggle={() => setExpanded(expanded === role ? null : role)}
            llmProviders={llmProviders}
            providerModels={providerModels}
            providerParams={providerParams}
            adminKey={adminKey}
            onTestResult={onTestResult}
            promptDefault={promptDefaults[ROLE_PROMPT_KEY[role] as string] ?? ""}
            promptKey={ROLE_PROMPT_KEY[role] as string}
          />
        ))}
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={copyDirectorToPerformer}
          className="text-xs font-medium text-admin-accent hover:text-admin-accent-hover underline underline-offset-2 transition-colors"
        >
          Copy Director settings to Performer
        </button>
        <button
          onClick={copyModeratorToClassifier}
          className="text-xs font-medium text-admin-accent hover:text-admin-accent-hover underline underline-offset-2 transition-colors"
        >
          Copy Moderator settings to Classifier
        </button>
      </div>

      {/* ── Post-processing ─────────────────────────────────────────── */}
      <div className="bg-admin-surface rounded-lg border border-admin-border overflow-hidden">
        <div className="px-5 py-3 flex items-center justify-between">
          <div>
            <span className="text-sm font-semibold text-admin-text">Post-processing</span>
            <span className="text-xs text-admin-faint ml-2">Humanizer — applied after Moderator, before Classifier</span>
          </div>
          {/* Master toggle */}
          <button
            onClick={() => onChange({ humanize_output: !config.humanize_output })}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${config.humanize_output ? "bg-admin-accent" : "bg-admin-border"}`}
          >
            <span className={`inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform ${config.humanize_output ? "translate-x-4" : "translate-x-1"}`} />
          </button>
        </div>

        {config.humanize_output && (
          <div className="px-5 pb-4 border-t border-admin-border pt-3 space-y-3">
            <p className="text-xs text-admin-muted">
              Set the probability (0–100%) for each transformation. 0 = never, 100 = always.
            </p>

            <div className="grid grid-cols-2 gap-x-8 gap-y-3">
              {([
                { key: "humanize_strip_hashtags",       label: "Strip hashtags",          desc: "Removes #hashtag tokens",                          def: 100 },
                { key: "humanize_strip_inverted_punct", label: "Remove ¿ / ¡",            desc: "Drops Spanish inverted punctuation",                def: 100 },
                { key: "humanize_word_subs",            label: "Word contractions",        desc: "que→q, xq→porque, tb→también, pa→para, x→por…",   def: 80  },
                { key: "humanize_drop_accents",         label: "Drop accents",             desc: "Per-message chance to strip all accents",           def: 40  },
                { key: "humanize_comma_spacing",        label: "Remove space after comma", desc: "Per-comma chance: hola,como vs hola, como",        def: 50  },
              ] as { key: keyof SimulationConfig; label: string; desc: string; def: number }[]).map(({ key, label, desc, def }) => {
                const val = (config[key] as number) ?? def
                return (
                  <div key={key}>
                    <div className="flex items-center justify-between mb-1">
                      <p className="text-xs font-medium text-admin-text">{label}</p>
                      <div className="flex items-center gap-1">
                        <input
                          type="number"
                          min={0} max={100}
                          value={val}
                          onChange={(e) => onChange({ [key]: Math.min(100, Math.max(0, parseInt(e.target.value) || 0)) } as Partial<SimulationConfig>)}
                          className="w-12 px-1.5 py-0.5 border border-admin-border rounded text-xs bg-admin-surface text-admin-text text-right focus:outline-none focus:border-admin-accent"
                        />
                        <span className="text-xs text-admin-faint">%</span>
                      </div>
                    </div>
                    <input
                      type="range" min={0} max={100} value={val}
                      onChange={(e) => onChange({ [key]: parseInt(e.target.value) } as Partial<SimulationConfig>)}
                      className="w-full h-1.5 accent-admin-accent"
                    />
                    <p className="text-xs text-admin-faint mt-0.5">{desc}</p>
                  </div>
                )
              })}

              {/* Emoji limit */}
              <div>
                <div className="flex items-center justify-between mb-1">
                  <p className="text-xs font-medium text-admin-text">Max emoji per message</p>
                  <div className="flex items-center gap-1">
                    <input
                      type="number" min={-1} max={10}
                      value={config.humanize_max_emoji ?? 1}
                      onChange={(e) => onChange({ humanize_max_emoji: parseInt(e.target.value) ?? 1 })}
                      className="w-12 px-1.5 py-0.5 border border-admin-border rounded text-xs bg-admin-surface text-admin-text text-right focus:outline-none focus:border-admin-accent"
                    />
                  </div>
                </div>
                <p className="text-xs text-admin-faint">-1 = unlimited · 0 = strip all</p>
              </div>
            </div>
          </div>
        )}
      </div>


    </div>
  )
}
