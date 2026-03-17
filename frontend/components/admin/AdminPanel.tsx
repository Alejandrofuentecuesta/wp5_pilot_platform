"use client"

import { useState, useCallback, useEffect } from "react"
import PassphraseGate from "./PassphraseGate"
import Dashboard from "./Dashboard"
import WizardShell from "./WizardShell"
import StepExperiment from "./steps/StepExperiment"
import StepSession from "./steps/StepSession"
import StepLLM, { type LLMTestResults } from "./steps/StepLLM"
import StepTreatments from "./steps/StepTreatments"
import StepTokens from "./steps/StepTokens"
import StepReview from "./steps/StepReview"
import { getMeta, saveConfig, updateConfig, listExperiments, getExperimentConfig } from "../../lib/admin-api"
import type {
  SimulationConfig,
  ExperimentalConfig,
  TokenConfig,
  AdminMeta,
} from "../../lib/admin-types"

type View = "dashboard" | "wizard"
export type AdminTheme = "light" | "dark"

// ── Frontend-owned defaults ─────────────────────────────────────────────────
// These are the starting values for a new experiment wizard.
// The backend validates; the frontend provides sensible defaults.

const DEFAULT_SIMULATION: SimulationConfig = {
  random_seed: 42,
  session_duration_minutes: 5,
  num_agents: 5,
  agent_names: ["", "", "", "", ""],
  agent_personas: [],
  messages_per_minute: 6,
  director_llm_provider: "anthropic",
  director_llm_model: "claude-haiku-4-5",
  director_temperature: 0.8,
  director_top_p: 0.8,
  director_max_tokens: 1024,
  performer_llm_provider: "mistral",
  performer_llm_model: "mistral-large-latest",
  performer_temperature: 0.8,
  performer_top_p: 0.8,
  performer_max_tokens: 256,
  moderator_llm_provider: "anthropic",
  moderator_llm_model: "claude-haiku-4-5",
  moderator_temperature: 0.2,
  moderator_top_p: 1.0,
  moderator_max_tokens: 256,
  classifier_llm_provider: "anthropic",
  classifier_llm_model: "claude-haiku-4-5",
  classifier_temperature: 0.2,
  classifier_top_p: 1.0,
  classifier_max_tokens: 256,
  evaluate_interval: 5,
  action_window_size: 5,
  performer_memory_size: 3,
}

const DEFAULT_EXPERIMENTAL: ExperimentalConfig = {
  chatroom_context: "",
  ecological_validity_criteria: "The conversation should be dialogic: agents should react to the state of the conversation, rather than talking past each other. There should be a mix of action types: approx. 30% message, 30% likes, 20% replies, 20% @mentions. Messages must be short (1-2 sentences, under 30 words) — brief, punchy contributions like in a real group chat. Tone and style should vary, with some containing emojis or punctuation. Messages should be 'reddit-like': informal, self-aware, and sometimes include internet humour, slang, and abbreviations.",
  redirect_url: "",
  groups: {
    condition_1: { features: ["news_article", "gate_until_user_post"], internal_validity_criteria: "" },
  },
}

const DEFAULT_TOKENS: TokenConfig = { groups: {} }

function getDefaultExperimentalConfig(): ExperimentalConfig {
  return {
    ...DEFAULT_EXPERIMENTAL,
    groups: Object.fromEntries(
      Object.entries(DEFAULT_EXPERIMENTAL.groups).map(([name, group]) => [
        name,
        {
          ...group,
          features: [...(group.features ?? [])],
          seed: group.seed ? { ...group.seed } : undefined,
        },
      ])
    ),
  }
}

/** Format a Date as a `datetime-local` input value (YYYY-MM-DDTHH:MM). */
function toLocalDatetimeString(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function defaultSchedule(): { startsAt: string; endsAt: string } {
  const now = new Date()
  const tomorrow = new Date(now.getTime() + 24 * 60 * 60 * 1000)
  return {
    startsAt: toLocalDatetimeString(now),
    endsAt: toLocalDatetimeString(tomorrow),
  }
}

export default function AdminPanel() {
  // Theme
  const [theme, setTheme] = useState<AdminTheme>("light")

  useEffect(() => {
    const saved = localStorage.getItem("admin-theme") as AdminTheme | null
    if (saved === "light" || saved === "dark") setTheme(saved)
  }, [])

  const toggleTheme = useCallback(() => {
    setTheme((prev) => {
      const next = prev === "light" ? "dark" : "light"
      localStorage.setItem("admin-theme", next)
      return next
    })
  }, [])

  // Auth — persist in sessionStorage so it survives refresh but clears on tab close
  const [adminKey, setAdminKey] = useState("")
  const [authenticated, setAuthenticated] = useState(false)
  const [restoringSession, setRestoringSession] = useState(true)

  useEffect(() => {
    const savedKey = sessionStorage.getItem("admin-key")
    if (savedKey) {
      handleAuthenticated(savedKey)
    } else {
      setRestoringSession(false)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // View toggle
  const [view, setView] = useState<View>("dashboard")

  // Wizard state
  const [step, setStep] = useState(0)
  const [experimentId, setExperimentId] = useState("")
  const [description, setDescription] = useState("")
  const [startsAt, setStartsAt] = useState(() => defaultSchedule().startsAt)
  const [endsAt, setEndsAt] = useState(() => defaultSchedule().endsAt)

  // Config state — initialized with frontend defaults for new experiments
  const [simulation, setSimulation] = useState<SimulationConfig>(DEFAULT_SIMULATION)
  const [experimental, setExperimental] = useState<ExperimentalConfig>(getDefaultExperimentalConfig())
  const [tokens, setTokens] = useState<TokenConfig>(DEFAULT_TOKENS)
  const [meta, setMeta] = useState<AdminMeta | null>(null)

  // Existing experiment IDs (for duplicate check)
  const [existingExperimentIds, setExistingExperimentIds] = useState<Set<string>>(new Set())

  // Track whether the user has attempted to advance past Step 1 (for deferred validation)
  const [sessionTouched, setSessionTouched] = useState(false)

  // Track LLM test results per role
  const [llmTestResults, setLlmTestResults] = useState<LLMTestResults>({
    director: false,
    performer: false,
    moderator: false,
    classifier: false,
  })
  const [editingExperimentId, setEditingExperimentId] = useState<string | null>(null)

  // Save state
  const [saving, setSaving] = useState(false)
  const [saveBanner, setSaveBanner] = useState<string | null>(null)
  const [saveError, setSaveError] = useState("")

  // Loading state for initial meta fetch
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState("")

  const handleAuthenticated = useCallback(async (key: string) => {
    setAdminKey(key)
    setLoading(true)
    setLoadError("")
    try {
      const [metaData, expList] = await Promise.all([
        getMeta(key),
        listExperiments(key).catch(() => ({ experiments: [] as { experiment_id: string }[] })),
      ])
      setMeta(metaData)
      setExistingExperimentIds(new Set(expList.experiments.map((e) => e.experiment_id)))
    } catch (e) {
      setLoadError(
        e instanceof Error ? e.message : "Failed to load platform metadata from server"
      )
      setLoading(false)
      setRestoringSession(false)
      sessionStorage.removeItem("admin-key")
      return
    }
    setLoading(false)
    setRestoringSession(false)
    setAuthenticated(true)
    sessionStorage.setItem("admin-key", key)
  }, [])

  const handleSimChange = useCallback((updates: Partial<SimulationConfig>) => {
    setSimulation((prev) => ({ ...prev, ...updates }))
  }, [])

  const handleLlmTestResult = useCallback((role: "director" | "performer" | "moderator" | "classifier", ok: boolean) => {
    setLlmTestResults((prev) => ({ ...prev, [role]: ok }))
  }, [])

  const handleSave = useCallback(async () => {
    if (!simulation || !experimental) return
    setSaving(true)
    setSaveBanner(null)
    setSaveError("")
    try {
      if (editingExperimentId) {
        await updateConfig(adminKey, editingExperimentId, {
          simulation,
          experimental,
          description,
          starts_at: startsAt ? new Date(startsAt).toISOString() : null,
          ends_at: endsAt ? new Date(endsAt).toISOString() : null,
        })
        setSaveBanner(`Experiment "${editingExperimentId}" updated successfully.`)
        setEditingExperimentId(null)
      } else {
        if (!tokens) return
        await saveConfig(adminKey, {
          simulation,
          experimental,
          tokens,
          experiment_id: experimentId,
          description,
          starts_at: startsAt ? new Date(startsAt).toISOString() : null,
          ends_at: endsAt ? new Date(endsAt).toISOString() : null,
        })
        setSaveBanner(`Experiment "${experimentId}" saved and activated. Participants can now join.`)
      }
      setView("dashboard")
      setStep(0)
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Save failed")
    }
    setSaving(false)
  }, [adminKey, simulation, experimental, tokens, experimentId, editingExperimentId, description, startsAt, endsAt])

  // Per-step validation — returns error message or null if valid
  const validateStep = useCallback((s: number): string | null => {
    switch (s) {
      case 0: {
        if (!experimentId.trim()) return "Experiment ID is required."
        if (!editingExperimentId && existingExperimentIds.has(experimentId.trim()))
          return "An experiment with this ID already exists. Choose a different ID."
        if (!description.trim()) return "Description is required."
        if (startsAt && endsAt && new Date(endsAt) <= new Date(startsAt))
          return "End date must be after start date."
        return null
      }
      case 1: {
        setSessionTouched(true)
        if (simulation.session_duration_minutes < 1) return "Session duration must be at least 1 minute."
        if (simulation.num_agents > 0) {
          const names = simulation.agent_names
          for (let i = 0; i < names.length; i++) {
            if (!names[i].trim()) return `Agent ${i + 1} name is required.`
            if (names.some((other, j) => j !== i && other.trim() === names[i].trim()))
              return `Agent name "${names[i]}" is duplicated.`
          }
        }
        if (simulation.evaluate_interval < 1) return "Validity check interval must be at least 1."
        if (simulation.action_window_size < 1) return "Action window size must be at least 1."
        if (simulation.performer_memory_size < 0) return "Performer memory size must be at least 0."
        return null
      }
      case 2: {
        for (const role of ["director", "performer", "moderator", "classifier"] as const) {
          const model = simulation[`${role}_llm_model` as keyof typeof simulation] as string
          if (!model.trim()) return `${role.charAt(0).toUpperCase() + role.slice(1)} model is required.`
        }
        const untested = (["director", "performer", "moderator"] as const).filter((r) => !llmTestResults[r])
        if (untested.length > 0) {
          const names = untested.map((r) => r.charAt(0).toUpperCase() + r.slice(1))
          return `Run a successful LLM test for: ${names.join(", ")}.`
        }
        return null
      }
      case 3: {
        const entries = Object.entries(experimental.groups)
        if (entries.length === 0) return "At least one treatment group is required."
        if (!experimental.chatroom_context.trim()) return "Chatroom context is required."
        if (!experimental.ecological_validity_criteria.trim()) return "Ecological validity criteria are required."
        for (const [name, group] of entries) {
          if (!name.trim()) return "All treatment groups must have a name."
          if (!group.internal_validity_criteria.trim()) return `Internal validity criteria for "${name}" is required.`
          if (group.features.includes("news_article")) {
            const seed = group.seed
            if (!seed || !seed.headline.trim() || !seed.body.trim())
              return `Seed article headline and body are required for group "${name}".`
          }
        }
        // Check for duplicate group names
        const names = entries.map(([n]) => n.trim())
        const uniqueNames = new Set(names)
        if (uniqueNames.size !== names.length) return "Treatment group names must be unique."
        return null
      }
      case 4: {
        if (editingExperimentId) return null
        const groupNames = Object.keys(experimental.groups)
        if (groupNames.length === 0) return "Define treatment groups first."
        const totalTokens = Object.values(tokens.groups).reduce((sum, arr) => sum + arr.length, 0)
        if (totalTokens === 0) return "Generate tokens before proceeding."
        // Check that token groups match current treatment groups
        const tokenGroupNames = Object.keys(tokens.groups).sort()
        const treatmentGroupNames = groupNames.sort()
        if (JSON.stringify(tokenGroupNames) !== JSON.stringify(treatmentGroupNames))
          return "Token groups don't match treatment groups. Regenerate tokens."
        return null
      }
      default:
        return null
    }
  }, [experimentId, existingExperimentIds, editingExperimentId, description, startsAt, endsAt, simulation, experimental, tokens, llmTestResults])

  const handleOpenWizard = useCallback(() => {
    // Reset wizard to fresh defaults for a new experiment
    setSimulation({ ...DEFAULT_SIMULATION })
    setExperimental(getDefaultExperimentalConfig())
    setTokens({ ...DEFAULT_TOKENS })
    setExperimentId("")
    setDescription("")
    const sched = defaultSchedule()
    setStartsAt(sched.startsAt)
    setEndsAt(sched.endsAt)
    setSessionTouched(false)
    setLlmTestResults({ director: false, performer: false, moderator: false, classifier: false })
    setEditingExperimentId(null)
    setSaveBanner(null)
    setSaveError("")
    setStep(0)
    setView("wizard")
    // Refresh existing experiment IDs
    if (adminKey) {
      listExperiments(adminKey)
        .then((res) => setExistingExperimentIds(new Set(res.experiments.map((e) => e.experiment_id))))
        .catch(() => {})
    }
  }, [adminKey])

  const handleEditExperiment = useCallback(async (expId: string) => {
    try {
      const { config, description: desc, starts_at, ends_at } = await getExperimentConfig(adminKey, expId)
      setSimulation(config.simulation)
      setExperimental(config.experimental)
      setExperimentId(expId)
      setDescription(desc || "")
      setStartsAt(starts_at ? starts_at.slice(0, 16) : "")
      setEndsAt(ends_at ? ends_at.slice(0, 16) : "")
      setEditingExperimentId(expId)
      setTokens({ groups: {} })
      setSessionTouched(false)
      setLlmTestResults({ director: true, performer: true, moderator: true, classifier: true })
      setSaveBanner(null)
      setSaveError("")
      setStep(0)
      setView("wizard")
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Failed to load experiment")
    }
  }, [adminKey])

  const handleDuplicateExperiment = useCallback(async (expId: string) => {
    try {
      const { config, description: desc, starts_at, ends_at } = await getExperimentConfig(adminKey, expId)
      const copyId = `${expId}_copy_${Date.now()}`
      setSimulation(config.simulation)
      setExperimental(config.experimental)
      setExperimentId(copyId)
      setDescription(desc ? `${desc} (copy)` : `Copy of ${expId}`)
      setStartsAt(starts_at ? starts_at.slice(0, 16) : "")
      setEndsAt(ends_at ? ends_at.slice(0, 16) : "")
      setEditingExperimentId(null)
      setTokens({ groups: {} })
      setSessionTouched(false)
      setLlmTestResults({ director: true, performer: true, moderator: true, classifier: true })
      setSaveBanner(null)
      setSaveError("")
      setStep(0)
      setView("wizard")
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Failed to duplicate experiment")
    }
  }, [adminKey])

  const handleBackToDashboard = useCallback(() => {
    setView("dashboard")
    setEditingExperimentId(null)
  }, [])

  if (!authenticated) {
    if (restoringSession) {
      return (
        <div data-admin-theme={theme} className="flex items-center justify-center h-dvh bg-admin-bg">
          <p className="text-admin-muted text-sm">Restoring session...</p>
        </div>
      )
    }
    return (
      <div data-admin-theme={theme}>
        <PassphraseGate onAuthenticated={handleAuthenticated} theme={theme} onToggleTheme={toggleTheme} />
        {loading && (
          <div className="fixed inset-0 flex items-center justify-center bg-black/30 z-50">
            <div className="bg-admin-surface rounded-xl shadow-lg p-6 max-w-md mx-4">
              <p className="text-sm text-admin-muted">Connecting to backend...</p>
            </div>
          </div>
        )}
        {loadError && (
          <div className="fixed inset-0 flex items-center justify-center bg-black/30 z-50">
            <div className="bg-admin-surface rounded-xl shadow-lg p-6 max-w-md mx-4 space-y-3">
              <h3 className="text-sm font-semibold text-red-600">Failed to connect</h3>
              <p className="text-sm text-admin-muted">{loadError}</p>
              <button
                onClick={() => setLoadError("")}
                className="px-4 py-1.5 text-xs font-medium bg-admin-raised hover:bg-admin-border rounded-lg transition-colors text-admin-text"
              >
                Dismiss
              </button>
            </div>
          </div>
        )}
      </div>
    )
  }

  if (!meta) {
    return (
      <div data-admin-theme={theme} className="flex items-center justify-center h-dvh bg-admin-bg">
        <p className="text-admin-muted text-sm">Loading...</p>
      </div>
    )
  }

  if (view === "dashboard") {
    return (
      <div data-admin-theme={theme}>
        <Dashboard
          adminKey={adminKey}
          onOpenWizard={handleOpenWizard}
          onEditExperiment={handleEditExperiment}
          onDuplicateExperiment={handleDuplicateExperiment}
          saveBanner={saveBanner}
          onDismissBanner={() => setSaveBanner(null)}
          theme={theme}
          onToggleTheme={toggleTheme}
        />
      </div>
    )
  }

  // Wizard view
  const groupNames = Object.keys(experimental.groups)

  const stepContent = [
    <StepExperiment
      key="experiment"
      experimentId={experimentId}
      setExperimentId={setExperimentId}
      description={description}
      setDescription={setDescription}
      startsAt={startsAt}
      setStartsAt={setStartsAt}
      endsAt={endsAt}
      setEndsAt={setEndsAt}
      redirectUrl={experimental.redirect_url}
      setRedirectUrl={(v) => setExperimental((prev) => ({ ...prev, redirect_url: v }))}
      adminKey={adminKey}
      isEditing={!!editingExperimentId}
    />,
    <StepSession
      key="session"
      config={simulation}
      onChange={handleSimChange}
      touched={sessionTouched}
    />,
    <StepLLM
      key="llm"
      config={simulation}
      onChange={handleSimChange}
      llmProviders={meta.llm_providers}
      providerModels={meta.provider_models}
      providerParams={meta.provider_params ?? {}}
      adminKey={adminKey}
      onTestResult={handleLlmTestResult}
    />,
    <StepTreatments
      key="treatments"
      config={experimental}
      onChange={setExperimental}
      availableFeatures={meta.available_features}
    />,
    <StepTokens
      key="tokens"
      tokens={tokens}
      setTokens={setTokens}
      groupNames={groupNames}
      adminKey={adminKey}
    />,
    <StepReview
      key="review"
      experimentId={experimentId}
      startsAt={startsAt}
      endsAt={endsAt}
      simulation={simulation}
      experimental={experimental}
      tokens={tokens}
      saveResult=""
      saveError={saveError}
    />,
  ]

  return (
    <div data-admin-theme={theme}>
      <WizardShell
        step={step}
        setStep={setStep}
        onSave={handleSave}
        saving={saving}
        onBack={handleBackToDashboard}
        theme={theme}
        onToggleTheme={toggleTheme}
        validateStep={validateStep}
      >
        {stepContent[step]}
      </WizardShell>
    </div>
  )
}
