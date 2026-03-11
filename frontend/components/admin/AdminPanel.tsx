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
  session_duration_minutes: 10,
  num_agents: 4,
  agent_names: ["Carlos", "Maria", "Pedro", "Laura"],
  agent_personas: [
    "Hombre de 45 anos, trabajador de fabrica, conservador, pragmatico, usa lenguaje directo y coloquial, a veces sarcastico. Le frustra la politica pero opina con firmeza.",
    "Mujer de 32 anos, profesora universitaria, progresista, argumentativa, usa datos y referencias. Paciente pero firme en sus convicciones.",
    "Hombre de 28 anos, programador, libertario, esceptico, usa humor negro e ironia. Cuestiona todo y desconfia de las instituciones.",
    "Mujer de 55 anos, ama de casa, moderada, emocional, habla desde la experiencia personal. Busca el consenso pero defiende sus valores tradicionales."
  ],
  messages_per_minute: 4,
  max_concurrent_turns: 2,
  director_llm_provider: "anthropic",
  director_llm_model: "claude-sonnet-4-20250514",
  director_temperature: 0.7,
  director_top_p: 0.9,
  director_max_tokens: 512,
  performer_llm_provider: "huggingface",
  performer_llm_model: "dphn/Dolphin-Mistral-24B-Venice-Edition:featherless-ai",
  performer_temperature: 0.8,
  performer_top_p: 0.9,
  performer_max_tokens: 256,
  moderator_llm_provider: "huggingface",
  moderator_llm_model: "meta-llama/Llama-3.1-8B-Instruct",
  moderator_temperature: 0.2,
  moderator_top_p: 1.0,
  moderator_max_tokens: 256,
  classifier_llm_provider: "huggingface",
  classifier_llm_model: "meta-llama/Llama-3.1-8B-Instruct",
  classifier_temperature: 0.2,
  classifier_top_p: 1.0,
  classifier_max_tokens: 256,
  classifier_prompt_template: `# Classifier Task

Infer the participant's stance from the participant messages and classify the agent message.

## Participant Messages
{PARTICIPANT_MESSAGES}

## Agent Message To Classify
{AGENT_MESSAGE}

Return ONLY a JSON object with keys:
- is_incivil (true/false)
- is_like_minded (true/false/null)
- inferred_participant_stance (short text)
- rationale (short text)`,
  context_window_size: 15,
  llm_concurrency_limit: 5,
}

const DEFAULT_EXPERIMENTAL: ExperimentalConfig = {
  chatroom_context: "Chatroom de discusion sobre temas politicos y sociales de actualidad. Los participantes son ciudadanos adultos con interes en el debate publico. El tono es informal, similar a Reddit o Twitter.",
  redirect_url: "",
  groups: {
    civil_pro: {
      features: [],
      treatment: "Los agentes deben comportarse de manera CIVIL y estar DE ACUERDO (PRO) con las opiniones del participante humano. Deben: validar y reforzar los puntos del participante, anadir argumentos que apoyen su posicion, mostrar entusiasmo moderado, expresar desacuerdos menores de forma constructiva si es necesario para parecer realistas, usar lenguaje informal pero cordial, sin ataques personales."
    },
    civil_against: {
      features: [],
      treatment: "Los agentes deben comportarse de manera CIVIL pero estar EN DESACUERDO (AGAINST) con las opiniones del participante humano. Deben: cuestionar respetuosamente los argumentos del participante, ofrecer contraargumentos basados en hechos o perspectivas alternativas, reconocer parcialmente los puntos validos antes de disentir, evitar ataques personales y mantener el foco en las ideas, usar lenguaje informal pero cordial."
    },
    incivil_pro: {
      features: [],
      treatment: "Los agentes deben comportarse de manera INCIVIL y estar DE ACUERDO (PRO) con las opiniones del participante humano. Deben: apoyar al participante mientras atacan agresivamente a quienes piensan diferente, usar lenguaje despectivo hacia los que no comparten la opinion, validar al participante con entusiasmo agresivo, crear un ambiente de nosotros vs ellos, usar sarcasmo y condescendencia hacia opiniones contrarias, menospreciar la inteligencia de quienes disienten."
    },
    incivil_against: {
      features: [],
      treatment: "Los agentes deben comportarse de manera INCIVIL y estar EN DESACUERDO (AGAINST) con las opiniones del participante humano. Deben: atacar directamente las opiniones del participante con desprecio, usar sarcasmo agresivo y condescendencia, cuestionar la inteligencia o conocimiento del participante, desestimar sus argumentos sin considerarlos seriamente, usar generalizaciones negativas, mostrar frustracion e indignacion, interrumpir y hablar sobre el participante ignorando sus puntos."
    },
  },
}

const DEFAULT_TOKENS: TokenConfig = { groups: {} }

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
  const [experimentId, setExperimentId] = useState("experimento_2x2_civility")
  const [description, setDescription] = useState("Estudio 2x2: Civilidad (civil/incivil) x Postura (pro/against). Investigacion sobre interacciones humano-IA en entornos de discusion politica.")
  const [startsAt, setStartsAt] = useState(() => defaultSchedule().startsAt)
  const [endsAt, setEndsAt] = useState(() => defaultSchedule().endsAt)

  // Config state — initialized with frontend defaults for new experiments
  const [simulation, setSimulation] = useState<SimulationConfig>(DEFAULT_SIMULATION)
  const [experimental, setExperimental] = useState<ExperimentalConfig>(DEFAULT_EXPERIMENTAL)
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

  // Edit mode state
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
        // Update existing experiment
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
        // Create new experiment
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
        // Only check for duplicates if NOT editing an existing experiment
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
        if (simulation.context_window_size < 1) return "Context window size must be at least 1."
        return null
      }
      case 2: {
        for (const role of ["director", "performer", "moderator", "classifier"] as const) {
          const model = simulation[`${role}_llm_model` as keyof typeof simulation] as string
          if (!model.trim()) return `${role.charAt(0).toUpperCase() + role.slice(1)} model is required.`
        }
        const untested = (["director", "performer", "moderator", "classifier"] as const).filter((r) => !llmTestResults[r])
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
        for (const [name, group] of entries) {
          if (!name.trim()) return "All treatment groups must have a name."
          if (!group.treatment.trim()) return `Treatment description for "${name}" is required.`
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
        // Skip token validation when editing (tokens already exist)
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
    setExperimental({ ...DEFAULT_EXPERIMENTAL })
    setTokens({ ...DEFAULT_TOKENS })
    setExperimentId(`experimento_${Date.now()}`)
    setDescription("Estudio 2x2: Civilidad (civil/incivil) x Postura (pro/against). Investigacion sobre interacciones humano-IA.")
    const sched = defaultSchedule()
    setStartsAt(sched.startsAt)
    setEndsAt(sched.endsAt)
    setSessionTouched(false)
    setLlmTestResults({ director: false, performer: false, moderator: false, classifier: false })
    setEditingExperimentId(null) // Reset edit mode
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
      // Mark LLM tests as passed since config was previously validated
      setLlmTestResults({ director: true, performer: true, moderator: true, classifier: true })
      setTokens({ groups: {} }) // Keep empty, not needed for edit
      setSessionTouched(false)
      setSaveBanner(null)
      setSaveError("")
      setStep(0)
      setView("wizard")
    } catch (e) {
      console.error("Failed to load experiment for editing", e)
    }
  }, [adminKey])


  const handleDuplicateExperiment = useCallback(async (sourceExperimentId: string) => {
    try {
      const { config, description: desc, starts_at, ends_at } = await getExperimentConfig(adminKey, sourceExperimentId)
      const copyId = `${sourceExperimentId}_copy_${Date.now()}`

      setSimulation(config.simulation)
      setExperimental(config.experimental)
      setExperimentId(copyId)
      setDescription(desc ? `${desc} (copy)` : `Copy of ${sourceExperimentId}`)
      setStartsAt(starts_at ? starts_at.slice(0, 16) : "")
      setEndsAt(ends_at ? ends_at.slice(0, 16) : "")
      setEditingExperimentId(null) // Duplicate creates a new experiment
      // Mark LLM tests as passed since copied config was previously validated
      setLlmTestResults({ director: true, performer: true, moderator: true })
      setTokens({ groups: {} }) // Require generating fresh tokens for the new experiment
      setSessionTouched(false)
      setSaveBanner(null)
      setSaveError("")
      setStep(0)
      setView("wizard")
    } catch (e) {
      console.error("Failed to duplicate experiment", e)
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
      saving={saving}
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
