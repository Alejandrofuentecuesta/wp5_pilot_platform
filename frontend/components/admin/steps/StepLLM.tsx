"use client"

import { useState } from "react"
import type { SimulationConfig, ProviderParamsMeta, TestLLMResult } from "../../../lib/admin-types"
import { testLlm } from "../../../lib/admin-api"

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
  classifier: "Evaluates each final agent message as incivil/civil and like-minded/not like-minded against the participant's inferred stance.",
}

const inputClass = "w-full px-3 py-2 border border-admin-border rounded-lg text-sm bg-admin-surface text-admin-text focus:outline-none focus:border-admin-accent focus:ring-1 focus:ring-admin-accent/30"

function providersForRole(role: Role, llmProviders: string[], currentProvider: string): string[] {
  if (role === "performer") {
    return llmProviders
  }

  const filtered = llmProviders.filter((provider) => provider !== "bsc")
  if (currentProvider === "bsc") {
    return ["bsc", ...filtered]
  }
  return filtered
}

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
}) {
  const prefix = role
  const provider = config[`${prefix}_llm_provider` as keyof SimulationConfig] as string
  const model = config[`${prefix}_llm_model` as keyof SimulationConfig] as string
  const temperature = config[`${prefix}_temperature` as keyof SimulationConfig] as number
  const topP = config[`${prefix}_top_p` as keyof SimulationConfig] as number
  const maxTokens = config[`${prefix}_max_tokens` as keyof SimulationConfig] as number

  const suggestedModels = providerModels[provider] ?? []
  const availableProviders = providersForRole(role, llmProviders, provider)
  const isCustomModel = suggestedModels.length > 0 && !suggestedModels.includes(model)
  const [showCustomInput, setShowCustomInput] = useState(isCustomModel)

  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<TestLLMResult | null>(null)

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
          {provider === "bsc" && (
            <p className="text-xs text-admin-faint">
              BSC Incivility is tuned for short social-media style replies and is recommended for the Performer role.
            </p>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-admin-muted mb-1">Provider</label>
              <select
                value={provider}
                onChange={(e) => handleProviderChange(e.target.value)}
                className={inputClass}
              >
                {availableProviders.map((p) => (
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
        </div>
      )}
    </div>
  )
}

export default function StepLLM({ config, onChange, llmProviders, providerModels, providerParams, adminKey, onTestResult }: StepLLMProps) {
  const [expanded, setExpanded] = useState<Role | null>("director")

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

      <div className="bg-admin-surface rounded-lg border border-admin-border p-5 space-y-4">
        <h3 className="text-sm font-semibold text-admin-muted uppercase tracking-wider mb-3">Shared</h3>
        <div>
          <label className="block text-xs font-medium text-admin-muted mb-1">
            Max concurrent LLM API calls (per stage)
          </label>
          <input
            type="number"
            min={1}
            value={config.llm_concurrency_limit}
            onChange={(e) => onChange({ llm_concurrency_limit: Math.max(1, parseInt(e.target.value) || 1) })}
            className="w-24 px-3 py-2 border border-admin-border rounded-lg text-sm bg-admin-surface text-admin-text focus:outline-none focus:border-admin-accent focus:ring-1 focus:ring-admin-accent/30"
          />
          <p className="text-xs text-admin-faint mt-1">Limits simultaneous requests to each LLM provider (Director, Performer, Moderator, Classifier independently). Increase for faster throughput; decrease if hitting API rate limits.</p>
        </div>

        <div>
          <label className="block text-xs font-medium text-admin-muted mb-1">
            Classifier Prompt Template
          </label>
          <textarea
            value={config.classifier_prompt_template || ""}
            onChange={(e) => onChange({ classifier_prompt_template: e.target.value })}
            rows={10}
            className={`${inputClass} font-mono text-xs`}
          />
          <p className="text-xs text-admin-faint mt-1">
            Available placeholders: <code>{"{PARTICIPANT_MESSAGES}"}</code>, <code>{"{AGENT_MESSAGE}"}</code>, <code>{"{CHATROOM_CONTEXT}"}</code>.
          </p>
        </div>
      </div>
    </div>
  )
}
