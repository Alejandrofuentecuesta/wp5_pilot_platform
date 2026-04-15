"use client"

import { useState, useEffect, useCallback, useRef } from "react"
import {
  listSessions,
  getTokenStats,
  listExperiments,
  resetSessions,
  deleteExperiment,
  activateExperiment,
  getExperimentConfig,
  getEvents,
  pauseExperiment,
  resumeExperiment,
  downloadSessionsCSV,
  downloadSessionBundle,
  getComplianceStats,
  getProviderKeys,
  setProviderKey,
} from "../../lib/admin-api"
import type { SessionSummary, TokenGroupStats, SimulationConfig, ExperimentalConfig, ComplianceGroupStats, ProviderKeyStatus } from "../../lib/admin-types"
import type { ExperimentSummary, AdminEvent } from "../../lib/admin-api"
import { API_BASE } from "../../lib/constants"
import type { AdminTheme } from "./AdminPanel"
import EvaluateTab from "./EvaluateTab"

interface DashboardProps {
  adminKey: string
  onOpenWizard: () => void
  onEditExperiment: (experimentId: string) => void
  onDuplicateExperiment: (experimentId: string) => void
  saveBanner: string | null
  onDismissBanner: () => void
  theme: AdminTheme
  onToggleTheme: () => void
}

type Tab = "overview" | "sessions" | "evaluate" | "compliance" | "logs" | "settings"

/* ── Theme toggle button ─────────────────────────────────────────────────── */

function ThemeToggle({ theme, onToggle }: { theme: AdminTheme; onToggle: () => void }) {
  return (
    <button
      onClick={onToggle}
      className="p-1.5 rounded-lg bg-admin-raised hover:bg-admin-border text-admin-muted hover:text-admin-text transition-colors"
      aria-label={`Switch to ${theme === "light" ? "dark" : "light"} mode`}
      title={`Switch to ${theme === "light" ? "dark" : "light"} mode`}
    >
      {theme === "light" ? (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
        </svg>
      ) : (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
        </svg>
      )}
    </button>
  )
}

/* ── Top bar ─────────────────────────────────────────────────────────────── */

function TopBar({
  experiments,
  selectedId,
  onSelect,
  backendOnline,
  onOpenWizard,
  saveBanner,
  onDismissBanner,
  theme,
  onToggleTheme,
}: {
  experiments: ExperimentSummary[]
  selectedId: string
  onSelect: (id: string) => void
  backendOnline: boolean | null
  onOpenWizard: () => void
  saveBanner: string | null
  onDismissBanner: () => void
  theme: AdminTheme
  onToggleTheme: () => void
}) {
  return (
    <div className="bg-admin-surface border-b border-admin-border sticky top-0 z-30">
      <div className="max-w-6xl mx-auto px-6 py-3 flex items-center gap-4">
        {/* Left: title */}
        <h1 className="text-sm font-semibold text-admin-text whitespace-nowrap">Admin Dashboard</h1>

        {/* Experiment selector */}
        {experiments.length > 0 && (
          <div className="flex items-center gap-2">
            <label className="text-xs text-admin-faint whitespace-nowrap">Experiment:</label>
            <select
              value={selectedId}
              onChange={(e) => onSelect(e.target.value)}
              className="text-sm font-mono border border-admin-border rounded-lg px-3 py-1.5 bg-admin-surface text-admin-text focus:outline-none focus:ring-2 focus:ring-admin-accent/20 focus:border-admin-accent/30 min-w-[180px]"
            >
              {experiments.map((exp) => (
                <option key={exp.experiment_id} value={exp.experiment_id}>
                  {exp.experiment_id}
                  {exp.description ? ` — ${exp.description.slice(0, 30)}` : ""}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Spacer */}
        <div className="flex-1" />

        {/* Status indicators */}
        <div className="flex items-center gap-3">
          <StatusDot label="Frontend" online={true} />
          <StatusDot label="Backend" online={backendOnline} />
        </div>

        {/* Theme toggle */}
        <ThemeToggle theme={theme} onToggle={onToggleTheme} />

        {/* New Experiment button */}
        <button
          onClick={onOpenWizard}
          className="shrink-0 px-4 py-1.5 text-xs font-medium bg-admin-accent text-white rounded-lg hover:bg-admin-accent-hover transition-colors"
        >
          + New Experiment
        </button>
      </div>

      {/* Save banner */}
      {saveBanner && (
        <div className="bg-admin-pastel-green border-t border-admin-border px-6 py-2 flex items-center justify-between">
          <p className="text-xs text-admin-pastel-green-text">{saveBanner}</p>
          <button onClick={onDismissBanner} className="text-admin-pastel-green-text hover:opacity-70 text-xs font-medium">
            Dismiss
          </button>
        </div>
      )}
    </div>
  )
}

function StatusDot({ label, online }: { label: string; online: boolean | null }) {
  const color =
    online === null
      ? "bg-admin-faint"
      : online
        ? "bg-green-500"
        : "bg-red-500"
  const text =
    online === null
      ? "Checking..."
      : online
        ? "Online"
        : "Offline"
  return (
    <div className="flex items-center gap-1.5">
      <span className={`inline-block w-2 h-2 rounded-full ${color}`} />
      <span className="text-xs text-admin-faint">{label}: <span className="font-medium text-admin-muted">{text}</span></span>
    </div>
  )
}

/* ── Tab bar ──────────────────────────────────────────────────────────────── */

const TAB_LABELS: { key: Tab; label: string; icon: string }[] = [
  { key: "overview", label: "Overview", icon: "M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" },
  { key: "sessions", label: "Sessions", icon: "M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" },
  { key: "evaluate", label: "Evaluate", icon: "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" },
  { key: "compliance", label: "Compliance", icon: "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" },
  { key: "logs", label: "Event Log", icon: "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" },
  { key: "settings", label: "Settings", icon: "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z" },
]

function TabBar({
  activeTab,
  onTabChange,
  sessionCount,
  errorCount,
}: {
  activeTab: Tab
  onTabChange: (tab: Tab) => void
  sessionCount: number
  errorCount: number
}) {
  return (
    <div className="bg-admin-surface border-b border-admin-border">
      <div className="max-w-6xl mx-auto px-6">
        <nav className="flex gap-0">
          {TAB_LABELS.map(({ key, label, icon }) => {
            const isActive = activeTab === key
            const badge =
              key === "sessions" && sessionCount > 0
                ? sessionCount
                : key === "logs" && errorCount > 0
                  ? errorCount
                  : null
            return (
              <button
                key={key}
                onClick={() => onTabChange(key)}
                className={`relative flex items-center gap-1.5 px-4 py-2.5 text-xs font-medium transition-colors ${
                  isActive
                    ? "text-admin-accent border-b-2 border-admin-accent"
                    : "text-admin-muted hover:text-admin-text border-b-2 border-transparent"
                }`}
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d={icon} />
                </svg>
                {label}
                {badge !== null && (
                  <span
                    className={`ml-1 inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full text-[10px] font-bold ${
                      key === "logs"
                        ? "bg-admin-danger-soft text-admin-danger-text"
                        : "bg-admin-accent-soft text-admin-accent"
                    }`}
                  >
                    {badge}
                  </span>
                )}
              </button>
            )
          })}
        </nav>
      </div>
    </div>
  )
}

/* ── Overview tab ────────────────────────────────────────────────────────── */

function OverviewTab({
  adminKey,
  experimentId,
  sessions,
  tokenStats,
  onEditExperiment,
  onDuplicateExperiment,
}: {
  adminKey: string
  experimentId: string
  sessions: SessionSummary[]
  tokenStats: TokenGroupStats[]
  onEditExperiment: (experimentId: string) => void
  onDuplicateExperiment: (experimentId: string) => void
}) {
  const [config, setConfig] = useState<{
    simulation: SimulationConfig
    experimental: ExperimentalConfig
  } | null>(null)
  const [description, setDescription] = useState("")
  const [createdAt, setCreatedAt] = useState("")
  const [configLoading, setConfigLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setConfigLoading(true)
    getExperimentConfig(adminKey, experimentId)
      .then((res) => {
        if (cancelled) return
        setConfig(res.config)
        setDescription(res.description)
        setCreatedAt(res.created_at)
        setConfigLoading(false)
      })
      .catch(() => {
        if (!cancelled) setConfigLoading(false)
      })
    return () => { cancelled = true }
  }, [adminKey, experimentId])

  const activeSessions = sessions.filter((s) => s.status === "active")
  const completedSessions = sessions.filter((s) => s.status === "ended" || s.status === "crashed")
  const crashedSessions = sessions.filter((s) => s.status === "crashed")
  const totalMessages = sessions.reduce((sum, s) => sum + s.message_count, 0)
  const totalTokens = tokenStats.reduce((sum, g) => sum + g.total, 0)
  const usedTokens = tokenStats.reduce((sum, g) => sum + g.used, 0)

  return (
    <div className="space-y-6">
      {/* Stat cards — pastel tinted */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="Active Sessions" value={activeSessions.length} pastel="purple" />
        <StatCard label="Total Messages" value={totalMessages} pastel="pink" />
        <StatCard
          label="Tokens Used"
          value={usedTokens}
          sub={totalTokens > 0 ? `of ${totalTokens}` : undefined}
          pastel="amber"
        />
        <StatCard
          label="Completed"
          value={completedSessions.length}
          sub={crashedSessions.length > 0 ? `${crashedSessions.length} crashed` : undefined}
          pastel="green"
        />
      </div>

      {/* Token progress */}
      <TokenProgress stats={tokenStats} />

      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => onEditExperiment(experimentId)}
          className="px-3 py-1.5 text-xs font-medium rounded-lg border border-admin-border text-admin-text hover:bg-admin-raised transition-colors"
        >
          Edit Experiment
        </button>
        <button
          onClick={() => onDuplicateExperiment(experimentId)}
          className="px-3 py-1.5 text-xs font-medium rounded-lg border border-admin-border text-admin-text hover:bg-admin-raised transition-colors"
        >
          Duplicate Experiment
        </button>
      </div>

      {/* Config summary */}
      <div className="bg-admin-surface rounded-lg border border-admin-border overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3 border-b border-admin-border">
          <h3 className="text-sm font-semibold text-admin-text">Experiment Configuration</h3>
          <button
            onClick={async () => {
              try {
                const res = await fetch(
                  `${API_BASE}/admin/tokens/csv/${encodeURIComponent(experimentId)}`,
                  { headers: { "X-Admin-Key": adminKey } },
                )
                if (!res.ok) throw new Error("Download failed")
                const blob = await res.blob()
                const url = URL.createObjectURL(blob)
                const a = document.createElement("a")
                a.href = url
                a.download = `${experimentId}_tokens.csv`
                a.click()
                URL.revokeObjectURL(url)
              } catch {
                // silently fail
              }
            }}
            className="text-xs font-medium text-admin-accent hover:text-admin-accent-hover transition-colors"
          >
            Download tokens (.csv)
          </button>
        </div>
        <div className="px-5 py-4 space-y-4 text-sm">
          {configLoading ? (
            <p className="text-sm text-admin-faint">Loading configuration...</p>
          ) : !config ? (
            <p className="text-sm text-admin-faint">Could not load configuration.</p>
          ) : (
            <>
              {/* Experiment meta */}
              <div className="space-y-1">
                <h4 className="text-xs font-semibold text-admin-faint uppercase tracking-wider">Experiment</h4>
                <div className="grid grid-cols-2 gap-x-6 gap-y-1">
                  <ConfigRow label="ID" value={experimentId} mono />
                  <ConfigRow label="Created" value={createdAt ? new Date(createdAt).toLocaleString() : "-"} />
                  {description && <ConfigRow label="Description" value={description} span2 />}
                </div>
              </div>

              {/* Session & timing */}
              <div className="space-y-1">
                <h4 className="text-xs font-semibold text-admin-faint uppercase tracking-wider">Session</h4>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-1">
                  <ConfigRow label="Duration" value={`${config.simulation.session_duration_minutes} min`} />
                  <ConfigRow label="Agents" value={`${config.simulation.num_agents} (${config.simulation.agent_names.filter(Boolean).join(", ") || "auto"})`} />
                  <ConfigRow label="Messages/min" value={config.simulation.messages_per_minute} />
                  <ConfigRow label="Evaluate interval" value={config.simulation.evaluate_interval} />
                  <ConfigRow label="Action window" value={config.simulation.action_window_size} />
                  <ConfigRow label="Random seed" value={config.simulation.random_seed} />
                </div>
              </div>

              {/* LLM config */}
              <div className="space-y-1">
                <h4 className="text-xs font-semibold text-admin-faint uppercase tracking-wider">LLM Pipeline</h4>
                <div className="space-y-2">
                  <LLMRow role="Director" provider={config.simulation.director_llm_provider} model={config.simulation.director_llm_model} temp={config.simulation.director_temperature} topP={config.simulation.director_top_p} maxTokens={config.simulation.director_max_tokens} />
                  <LLMRow role="Performer" provider={config.simulation.performer_llm_provider} model={config.simulation.performer_llm_model} temp={config.simulation.performer_temperature} topP={config.simulation.performer_top_p} maxTokens={config.simulation.performer_max_tokens} />
                  <LLMRow role="Moderator" provider={config.simulation.moderator_llm_provider} model={config.simulation.moderator_llm_model} temp={config.simulation.moderator_temperature} topP={config.simulation.moderator_top_p} maxTokens={config.simulation.moderator_max_tokens} />
                </div>
              </div>

              {/* Treatment groups */}
              <div className="space-y-1">
                <h4 className="text-xs font-semibold text-admin-faint uppercase tracking-wider">Treatment Groups</h4>
                <ConfigRow label="Chatroom context" value={config.experimental.chatroom_context || "(none)"} span2 />
                <div className="space-y-2 mt-2">
                  {Object.entries(config.experimental.groups).map(([name, group]) => (
                    <div key={name} className="bg-admin-raised rounded-lg px-3 py-2 space-y-1 border border-admin-border">
                      <p className="font-mono text-xs font-semibold text-admin-text">{name}</p>
                      <p className="text-xs text-admin-muted">
                        <span className="text-admin-faint">Internal validity:</span> {group.internal_validity_criteria || "(none)"}
                      </p>
                      {group.features.length > 0 && (
                        <p className="text-xs text-admin-muted">
                          <span className="text-admin-faint">Features:</span> {group.features.join(", ")}
                        </p>
                      )}
                      {group.seed && (
                        <p className="text-xs text-admin-muted">
                          <span className="text-admin-faint">Seed article:</span> {group.seed.headline}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

/* ── Sessions tab ────────────────────────────────────────────────────────── */

function SessionsTab({
  adminKey,
  experimentId,
  sessions,
}: {
  adminKey: string
  experimentId: string
  sessions: SessionSummary[]
}) {
  const [statusFilter, setStatusFilter] = useState<string>("")
  const [groupFilter, setGroupFilter] = useState<string>("")
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState("")

  const groups = Array.from(new Set(sessions.map((s) => s.treatment_group))).sort()
  const statuses = Array.from(new Set(sessions.map((s) => s.status))).sort()

  const filtered = sessions.filter((s) => {
    if (statusFilter && s.status !== statusFilter) return false
    if (groupFilter && s.treatment_group !== groupFilter) return false
    return true
  })

  const activeSessions = filtered.filter((s) => s.status === "active")
  const completedSessions = filtered.filter((s) => s.status !== "active")

  const handleExport = async () => {
    setExporting(true)
    setExportError("")
    try {
      await downloadSessionsCSV(adminKey, experimentId)
    } catch (err) {
      setExportError(err instanceof Error ? err.message : "CSV export failed")
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="bg-admin-surface rounded-lg border border-admin-border px-4 py-3 flex items-center gap-4 flex-wrap">
        <span className="text-xs font-medium text-admin-faint uppercase tracking-wider">Filters</span>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="text-xs border border-admin-border rounded-lg px-2.5 py-1.5 bg-admin-surface text-admin-text focus:outline-none focus:ring-1 focus:ring-admin-accent/20"
        >
          <option value="">All statuses</option>
          {statuses.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select
          value={groupFilter}
          onChange={(e) => setGroupFilter(e.target.value)}
          className="text-xs border border-admin-border rounded-lg px-2.5 py-1.5 bg-admin-surface text-admin-text focus:outline-none focus:ring-1 focus:ring-admin-accent/20"
        >
          <option value="">All groups</option>
          {groups.map((g) => (
            <option key={g} value={g}>{g}</option>
          ))}
        </select>
        <span className="text-xs text-admin-faint ml-auto">
          {filtered.length} of {sessions.length} session{sessions.length !== 1 ? "s" : ""}
        </span>
        <button
          onClick={handleExport}
          disabled={!experimentId || exporting}
          className="px-3 py-1.5 text-xs font-medium border border-admin-border text-admin-text rounded-lg hover:bg-admin-border/30 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {exporting ? "Exporting..." : "Export sessions CSV"}
        </button>
      </div>

      {exportError && (
        <div className="bg-admin-surface rounded-lg border border-admin-border p-3 text-xs text-red-600">
          {exportError}
        </div>
      )}

      {sessions.length === 0 ? (
        <div className="text-center py-12">
          <p className="text-sm text-admin-faint">No sessions yet. Sessions will appear here as participants join.</p>
        </div>
      ) : (
        <>
          <SessionTable
            adminKey={adminKey}
            experimentId={experimentId}
            sessions={activeSessions}
            title={`Active Sessions (${activeSessions.length})`}
          />
          <SessionTable
            adminKey={adminKey}
            experimentId={experimentId}
            sessions={completedSessions}
            title={`Completed Sessions (${completedSessions.length})`}
            showEndReason
          />
        </>
      )}
    </div>
  )
}

/* ── Event log tab ───────────────────────────────────────────────────────── */

const EVENT_COLORS: Record<string, { light: string; dark: string }> = {
  session_start: { light: "text-green-700 bg-green-50", dark: "text-emerald-300 bg-emerald-900/30" },
  session_end: { light: "text-amber-700 bg-amber-50", dark: "text-amber-300 bg-amber-900/30" },
  message: { light: "text-blue-700 bg-blue-50", dark: "text-blue-300 bg-blue-900/30" },
  llm_call: { light: "text-purple-700 bg-purple-50", dark: "text-purple-300 bg-purple-900/30" },
  error: { light: "text-red-700 bg-red-50", dark: "text-red-300 bg-red-900/30" },
  message_like: { light: "text-pink-700 bg-pink-50", dark: "text-pink-300 bg-pink-900/30" },
  message_report: { light: "text-orange-700 bg-orange-50", dark: "text-orange-300 bg-orange-900/30" },
  user_block: { light: "text-red-700 bg-red-50", dark: "text-red-300 bg-red-900/30" },
  websocket_attach: { light: "text-cyan-700 bg-cyan-50", dark: "text-cyan-300 bg-cyan-900/30" },
  websocket_detach: { light: "text-gray-600 bg-gray-50", dark: "text-gray-400 bg-gray-800/30" },
}

function summarizeEvent(evt: AdminEvent): string {
  const d = evt.data
  switch (evt.event_type) {
    case "session_start":
      return `Session started (group: ${d.treatment_group || "?"})`
    case "session_end":
      return `Session ended: ${d.reason || "unknown"}`
    case "message":
      return `${d.sender || "?"}: ${String(d.content || "").slice(0, 80)}${String(d.content || "").length > 80 ? "..." : ""}`
    case "llm_call": {
      const err = d.error ? ` [ERROR: ${String(d.error).slice(0, 40)}]` : ""
      return `LLM call (${d.agent_name || "?"})${err}`
    }
    case "error":
      return `${d.error_type || "error"}: ${String(d.error_message || "").slice(0, 80)}`
    case "message_like":
      return `${d.user || "?"} ${d.action || "liked"} a message`
    case "message_report":
      return `${d.user || "?"} ${d.action || "reported"} a message${d.reason ? `: ${d.reason}` : ""}`
    case "user_block":
      return `${d.by || "?"} blocked ${d.agent_name || "?"}`
    case "websocket_attach":
      return `WebSocket connected (replayed ${d.replayed_messages ?? "?"} messages)`
    case "websocket_detach":
      return `WebSocket disconnected`
    default:
      return JSON.stringify(d).slice(0, 100)
  }
}

function EventLogTab({ adminKey, experimentId, theme }: { adminKey: string; experimentId: string; theme: AdminTheme }) {
  const [events, setEvents] = useState<AdminEvent[]>([])
  const [autoScroll, setAutoScroll] = useState(true)
  const [filter, setFilter] = useState("")
  const cursorRef = useRef(0)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setEvents([])
    cursorRef.current = 0
  }, [experimentId])

  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      if (cancelled) return
      try {
        const res = await getEvents(adminKey, experimentId, cursorRef.current)
        if (cancelled || res.events.length === 0) return
        const maxId = Math.max(...res.events.map((e) => e.id))
        cursorRef.current = maxId
        setEvents((prev) => {
          const combined = [...prev, ...res.events]
          return combined.length > 1000 ? combined.slice(-1000) : combined
        })
      } catch {
        // silently retry next tick
      }
    }
    poll()
    const interval = setInterval(poll, 3000)
    return () => { cancelled = true; clearInterval(interval) }
  }, [adminKey, experimentId])

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [events, autoScroll])

  const filteredEvents = filter
    ? events.filter((e) => e.event_type === filter)
    : events

  const errorCount = events.filter((e) => e.event_type === "error").length
  const eventTypes = Array.from(new Set(events.map((e) => e.event_type))).sort()

  const handleDownload = () => {
    const lines = events.map((evt) => {
      const time = new Date(evt.occurred_at).toISOString()
      return `${time}\t${evt.session_id}\t${evt.event_type}\t${summarizeEvent(evt)}`
    })
    const content = "timestamp\tsession_id\tevent_type\tsummary\n" + lines.join("\n")
    const blob = new Blob([content], { type: "text/tab-separated-values" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `${experimentId}_events.tsv`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="bg-admin-surface rounded-lg border border-admin-border overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center gap-3 px-4 py-2.5 border-b border-admin-border bg-admin-raised">
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="text-xs border border-admin-border rounded px-2 py-1 bg-admin-surface text-admin-text focus:outline-none focus:ring-1 focus:ring-admin-accent/20"
        >
          <option value="">All events ({events.length})</option>
          {eventTypes.map((t) => (
            <option key={t} value={t}>
              {t} ({events.filter((e) => e.event_type === t).length})
            </option>
          ))}
        </select>
        {errorCount > 0 && (
          <button
            onClick={() => setFilter(filter === "error" ? "" : "error")}
            className={`text-xs px-2 py-0.5 rounded font-medium transition-colors ${
              filter === "error"
                ? "bg-red-600 text-white"
                : "bg-admin-danger-soft text-admin-danger-text hover:opacity-80"
            }`}
          >
            {errorCount} error{errorCount !== 1 ? "s" : ""}
          </button>
        )}
        <div className="flex-1" />
        <button
          onClick={handleDownload}
          disabled={events.length === 0}
          className="text-xs font-medium text-admin-muted hover:text-admin-text disabled:text-admin-faint disabled:cursor-not-allowed transition-colors"
        >
          Download log
        </button>
        <label className="flex items-center gap-1.5 text-xs text-admin-muted cursor-pointer select-none">
          <input
            type="checkbox"
            checked={autoScroll}
            onChange={(e) => setAutoScroll(e.target.checked)}
            className="rounded border-admin-border text-admin-accent focus:ring-admin-accent/20"
          />
          Auto-scroll
        </label>
      </div>

      {/* Event list */}
      <div
        ref={scrollRef}
        className="h-[500px] overflow-y-auto font-mono text-xs leading-relaxed"
        onScroll={() => {
          if (!scrollRef.current) return
          const { scrollTop, scrollHeight, clientHeight } = scrollRef.current
          const atBottom = scrollHeight - scrollTop - clientHeight < 40
          if (!atBottom && autoScroll) setAutoScroll(false)
          if (atBottom && !autoScroll) setAutoScroll(true)
        }}
      >
        {filteredEvents.length === 0 ? (
          <p className="px-4 py-6 text-center text-admin-faint font-sans text-sm">
            No events yet. Events will appear here as sessions run.
          </p>
        ) : (
          <table className="w-full">
            <tbody>
              {filteredEvents.map((evt) => {
                const colors = EVENT_COLORS[evt.event_type]
                const colorClass = colors
                  ? (theme === "dark" ? colors.dark : colors.light)
                  : (theme === "dark" ? "text-gray-400 bg-gray-800/30" : "text-gray-600 bg-gray-50")
                const time = new Date(evt.occurred_at).toLocaleTimeString()
                return (
                  <tr key={evt.id} className="border-b border-admin-border/50 hover:bg-admin-raised/50">
                    <td className="px-3 py-1 text-admin-faint whitespace-nowrap align-top w-16">
                      {time}
                    </td>
                    <td className="px-1 py-1 whitespace-nowrap align-top w-6">
                      <span className="text-admin-faint" title={evt.session_id}>
                        {evt.session_id.slice(0, 4)}
                      </span>
                    </td>
                    <td className="px-1 py-1 whitespace-nowrap align-top">
                      <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium ${colorClass}`}>
                        {evt.event_type}
                      </span>
                    </td>
                    <td className="px-3 py-1 text-admin-muted break-all">
                      {summarizeEvent(evt)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

/* ── Provider API Keys panel ─────────────────────────────────────────────── */

const PROVIDER_LABELS: Record<string, { label: string; docsUrl?: string }> = {
  anthropic:   { label: "Anthropic (Claude)" },
  gemini:      { label: "Google Gemini" },
  huggingface: { label: "HuggingFace Inference" },
  mistral:     { label: "Mistral" },
  konstanz:    { label: "Konstanz vLLM" },
  bsc:         { label: "BSC Incivility API" },
}

function ProviderKeysPanel({ adminKey }: { adminKey: string }) {
  const [status, setStatus] = useState<Record<string, ProviderKeyStatus> | null>(null)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<string | null>(null)      // provider being edited
  const [draftKey, setDraftKey] = useState("")
  const [draftExtra, setDraftExtra] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [feedback, setFeedback] = useState<{ provider: string; ok: boolean; msg: string } | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await getProviderKeys(adminKey)
      setStatus(data)
    } catch {
      /* ignore — show stale data */
    }
    setLoading(false)
  }, [adminKey])

  useEffect(() => { load() }, [load])

  const startEdit = (provider: string) => {
    setEditing(provider)
    setDraftKey("")
    setDraftExtra({})
    setFeedback(null)
  }

  const cancelEdit = () => {
    setEditing(null)
    setDraftKey("")
    setDraftExtra({})
  }

  const handleSave = async (provider: string) => {
    if (!draftKey.trim()) return
    setSaving(true)
    setFeedback(null)
    try {
      const extra = Object.keys(draftExtra).length > 0 ? draftExtra : undefined
      await setProviderKey(adminKey, provider, draftKey.trim(), extra)
      setFeedback({ provider, ok: true, msg: "Key saved — effective immediately, no restart needed." })
      setEditing(null)
      setDraftKey("")
      setDraftExtra({})
      await load()
    } catch (e) {
      setFeedback({ provider, ok: false, msg: e instanceof Error ? e.message : "Save failed" })
    }
    setSaving(false)
  }

  return (
    <div className="bg-admin-surface rounded-lg border border-admin-border overflow-hidden">
      <div className="px-5 py-3 border-b border-admin-border bg-admin-raised flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-admin-text">API Keys</h3>
          <p className="text-xs text-admin-muted mt-0.5">
            Keys are stored in the server&apos;s <code>.env</code> file only — never in the database or returned to the browser.
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="text-xs text-admin-accent hover:underline disabled:opacity-50"
        >
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      <div className="divide-y divide-admin-border">
        {status === null && loading && (
          <div className="px-5 py-4 text-sm text-admin-muted">Loading…</div>
        )}
        {status !== null && Object.entries(status).map(([provider, info]) => {
          const label = PROVIDER_LABELS[provider]?.label ?? provider
          const isEditing = editing === provider

          return (
            <div key={provider} className="px-5 py-4 space-y-3">
              <div className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-3 min-w-0">
                  <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold flex-shrink-0 ${info.configured ? "bg-green-500/10 text-green-600 dark:text-green-400" : "bg-admin-border text-admin-muted"}`}>
                    <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${info.configured ? "bg-green-500" : "bg-admin-muted"}`} />
                    {info.configured ? "Configured" : "Not set"}
                  </span>
                  <span className="text-sm font-medium text-admin-text truncate">{label}</span>
                  <span className="text-xs text-admin-faint font-mono hidden sm:block">{info.key_var}</span>
                </div>
                {!isEditing && (
                  <button
                    type="button"
                    onClick={() => startEdit(provider)}
                    className="text-xs font-medium px-2.5 py-1 rounded-lg border border-admin-border hover:border-admin-accent text-admin-muted hover:text-admin-accent transition-colors flex-shrink-0"
                  >
                    {info.configured ? "Update" : "Add key"}
                  </button>
                )}
              </div>

              {/* Extra vars (e.g. BSC endpoint URL) — show current status even when not editing */}
              {info.extra && !isEditing && (
                <div className="pl-8 space-y-1">
                  {Object.entries(info.extra).map(([varName, extraInfo]) => (
                    <div key={varName} className="flex items-center gap-2 text-xs text-admin-muted">
                      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${extraInfo.configured ? "bg-green-500" : "bg-admin-muted"}`} />
                      <span className="font-mono">{varName}</span>
                      <span className="text-admin-faint">({extraInfo.label})</span>
                      <span>{extraInfo.configured ? "— set" : "— not set"}</span>
                    </div>
                  ))}
                </div>
              )}

              {isEditing && (
                <div className="pl-0 space-y-3 pt-1">
                  <div>
                    <label className="block text-xs font-medium text-admin-muted mb-1">
                      New value for <code>{info.key_var}</code>
                    </label>
                    <input
                      type="password"
                      autoComplete="off"
                      value={draftKey}
                      onChange={(e) => setDraftKey(e.target.value)}
                      placeholder="Paste your API key here"
                      className="w-full px-3 py-2 border border-admin-border rounded-lg text-sm bg-admin-bg text-admin-text font-mono focus:outline-none focus:border-admin-accent focus:ring-1 focus:ring-admin-accent/30"
                    />
                    <p className="text-xs text-admin-faint mt-1">
                      The key is sent over HTTPS and written directly to the server&apos;s <code>.env</code> file. It is never stored in the database or shown again.
                    </p>
                  </div>

                  {/* Extra fields (e.g. BSC_API_BASE_URL) */}
                  {info.extra && Object.entries(info.extra).map(([varName, extraInfo]) => (
                    <div key={varName}>
                      <label className="block text-xs font-medium text-admin-muted mb-1">
                        <code>{varName}</code> — {extraInfo.label}
                        {extraInfo.configured && <span className="ml-1 text-admin-faint">(currently set — leave blank to keep existing)</span>}
                      </label>
                      <input
                        type="text"
                        autoComplete="off"
                        value={draftExtra[varName] ?? ""}
                        onChange={(e) => setDraftExtra((prev) => ({ ...prev, [varName]: e.target.value }))}
                        placeholder={extraInfo.configured ? "Leave blank to keep existing value" : "e.g. http://212.128.226.126/incivility/api/v1"}
                        className="w-full px-3 py-2 border border-admin-border rounded-lg text-sm bg-admin-bg text-admin-text font-mono focus:outline-none focus:border-admin-accent focus:ring-1 focus:ring-admin-accent/30"
                      />
                    </div>
                  ))}

                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => handleSave(provider)}
                      disabled={saving || !draftKey.trim()}
                      className="px-3 py-1.5 rounded-lg bg-admin-accent text-white text-xs font-medium hover:bg-admin-accent/90 disabled:opacity-50 transition-colors"
                    >
                      {saving ? "Saving…" : "Save key"}
                    </button>
                    <button
                      type="button"
                      onClick={cancelEdit}
                      disabled={saving}
                      className="px-3 py-1.5 rounded-lg border border-admin-border text-xs font-medium text-admin-muted hover:text-admin-text transition-colors"
                    >
                      Cancel
                    </button>
                  </div>

                  {feedback?.provider === provider && (
                    <p className={`text-xs font-medium ${feedback.ok ? "text-green-600 dark:text-green-400" : "text-red-500"}`}>
                      {feedback.msg}
                    </p>
                  )}
                </div>
              )}

              {/* Feedback shown after edit closed */}
              {!isEditing && feedback?.provider === provider && (
                <p className={`text-xs font-medium pl-0 ${feedback.ok ? "text-green-600 dark:text-green-400" : "text-red-500"}`}>
                  {feedback.msg}
                </p>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

/* ── Settings tab (danger zone) ──────────────────────────────────────────── */

type DangerAction = "reset_sessions" | "delete_experiment"

function SettingsTab({
  adminKey,
  experiments,
  selectedExperimentId,
  onRefresh,
}: {
  adminKey: string
  experiments: ExperimentSummary[]
  selectedExperimentId: string
  onRefresh: () => void
}) {
  const [typedId, setTypedId] = useState("")
  const [confirming, setConfirming] = useState<DangerAction | null>(null)
  const [feedback, setFeedback] = useState<{ msg: string; ok: boolean } | null>(null)
  const [pauseLoading, setPauseLoading] = useState(false)
  const [pauseFeedback, setPauseFeedback] = useState<{ msg: string; ok: boolean } | null>(null)

  const selectedExperiment = experiments.find((e) => e.experiment_id === selectedExperimentId)

  const handleTogglePause = async () => {
    if (!selectedExperiment) return
    setPauseLoading(true)
    setPauseFeedback(null)
    try {
      if (selectedExperiment.paused) {
        await resumeExperiment(adminKey, selectedExperiment.experiment_id)
        setPauseFeedback({ msg: `Experiment "${selectedExperiment.experiment_id}" resumed — participants can join again.`, ok: true })
      } else {
        await pauseExperiment(adminKey, selectedExperiment.experiment_id)
        setPauseFeedback({ msg: `Experiment "${selectedExperiment.experiment_id}" paused — new participants will be turned away.`, ok: true })
      }
      onRefresh()
    } catch (e) {
      setPauseFeedback({ msg: e instanceof Error ? e.message : "Action failed", ok: false })
    }
    setPauseLoading(false)
    setTimeout(() => setPauseFeedback(null), 5000)
  }

  const matchedExperiment = experiments.find((e) => e.experiment_id === typedId.trim())
  const canAct = !!matchedExperiment

  const handleResetSessions = async () => {
    if (!matchedExperiment) return
    setConfirming(null)
    try {
      const res = await resetSessions(adminKey, typedId.trim())
      setFeedback({ msg: `Reset ${res.sessions_deleted} session(s) for "${res.experiment_id}" — config and tokens preserved`, ok: true })
      setTypedId("")
      onRefresh()
    } catch (e) {
      setFeedback({ msg: e instanceof Error ? e.message : "Reset failed", ok: false })
    }
    setTimeout(() => setFeedback(null), 5000)
  }

  const handleDeleteExperiment = async () => {
    if (!matchedExperiment) return
    setConfirming(null)
    try {
      const res = await deleteExperiment(adminKey, typedId.trim())
      setFeedback({ msg: `Deleted experiment "${res.experiment_id}" and all associated data`, ok: true })
      setTypedId("")
      onRefresh()
    } catch (e) {
      setFeedback({ msg: e instanceof Error ? e.message : "Delete failed", ok: false })
    }
    setTimeout(() => setFeedback(null), 5000)
  }

  return (
    <div className="space-y-6">
      {/* API Key management */}
      <ProviderKeysPanel adminKey={adminKey} />

      {/* Experiment control — pause/resume */}
      {selectedExperiment && (
        <div className="bg-admin-surface rounded-lg border border-admin-pastel-amber-text/20 overflow-hidden">
          <div className="px-5 py-3 border-b border-admin-pastel-amber-text/20 bg-admin-pastel-amber">
            <h3 className="text-sm font-semibold text-admin-pastel-amber-text">Experiment Control</h3>
            <p className="text-xs text-admin-pastel-amber-text/70 mt-0.5">
              Manual control over participant access for &ldquo;{selectedExperiment.experiment_id}&rdquo;.
            </p>
          </div>

          <div className="px-5 py-4 space-y-4">
            <div className="text-xs text-admin-muted leading-relaxed space-y-2">
              <p>
                Ordinarily, participants can use their tokens and take the study at any time within the configured
                participation window
                {selectedExperiment.starts_at && selectedExperiment.ends_at ? (
                  <> ({new Date(selectedExperiment.starts_at).toLocaleString()} &ndash; {new Date(selectedExperiment.ends_at).toLocaleString()})</>
                ) : selectedExperiment.starts_at ? (
                  <> (from {new Date(selectedExperiment.starts_at).toLocaleString()})</>
                ) : selectedExperiment.ends_at ? (
                  <> (until {new Date(selectedExperiment.ends_at).toLocaleString()})</>
                ) : null}.
                Use the button below if you need to temporarily prevent new participants from joining.
              </p>
              <p>
                Pausing does <strong>not</strong> affect sessions already in progress — it only prevents new tokens from being consumed.
              </p>
            </div>

            <div className="flex items-center gap-3">
              <button
                onClick={handleTogglePause}
                disabled={pauseLoading}
                className={`px-4 py-2 text-xs font-medium rounded-lg transition-colors ${
                  selectedExperiment.paused
                    ? "text-admin-pastel-green-text bg-admin-pastel-green border border-admin-pastel-green-text/20 hover:opacity-80"
                    : "text-admin-pastel-amber-text bg-admin-pastel-amber border border-admin-pastel-amber-text/20 hover:opacity-80"
                } ${pauseLoading ? "opacity-50 cursor-not-allowed" : ""}`}
              >
                {pauseLoading
                  ? "Updating..."
                  : selectedExperiment.paused
                    ? "Resume Experiment"
                    : "Pause Experiment"}
              </button>
              {selectedExperiment.paused && (
                <span className="inline-flex items-center gap-1.5 text-xs font-medium text-admin-pastel-amber-text">
                  <span className="w-2 h-2 rounded-full bg-admin-pastel-amber-text animate-pulse" />
                  Currently paused
                </span>
              )}
            </div>

            {pauseFeedback && (
              <p className={`text-xs rounded px-3 py-1.5 ${
                pauseFeedback.ok ? "text-admin-pastel-green-text bg-admin-pastel-green" : "text-admin-danger-text bg-admin-danger-soft"
              }`}>
                {pauseFeedback.msg}
              </p>
            )}
          </div>
        </div>
      )}

      {/* Danger zone */}
      <div className="bg-admin-surface rounded-lg border border-admin-danger-border overflow-hidden">
        <div className="px-5 py-3 border-b border-admin-danger-border bg-admin-danger-soft">
          <h3 className="text-sm font-semibold text-admin-danger-text">Danger Zone</h3>
          <p className="text-xs text-admin-danger-text/70 mt-0.5">
            Destructive actions that cannot be undone. Type an experiment ID to enable the options below.
          </p>
        </div>

        <div className="px-5 py-4 space-y-4">
          {experiments.length > 0 && (
            <>
              <div>
                <label className="block text-xs font-medium text-admin-muted mb-1">
                  Experiment ID:
                </label>
                <input
                  type="text"
                  value={typedId}
                  onChange={(e) => setTypedId(e.target.value)}
                  placeholder="e.g. my_experiment"
                  className="w-full max-w-sm px-3 py-2 border border-admin-danger-border rounded-lg text-sm font-mono bg-admin-surface text-admin-text focus:outline-none focus:border-red-400 focus:ring-1 focus:ring-red-300/40"
                />
                {typedId.trim() && !canAct && (
                  <p className="text-[11px] text-admin-danger-text mt-1">
                    No experiment matching &ldquo;{typedId.trim()}&rdquo;
                  </p>
                )}
              </div>

              <div className="flex gap-2 max-w-sm">
                <button
                  onClick={() => setConfirming("reset_sessions")}
                  disabled={!canAct}
                  className={`flex-1 px-4 py-2 text-xs font-medium rounded-lg transition-colors ${
                    canAct
                      ? "text-admin-pastel-amber-text bg-admin-pastel-amber border border-admin-pastel-amber-text/20 hover:opacity-80"
                      : "text-admin-faint bg-admin-raised cursor-not-allowed"
                  }`}
                >
                  Reset Sessions
                </button>
                <button
                  onClick={() => setConfirming("delete_experiment")}
                  disabled={!canAct}
                  className={`flex-1 px-4 py-2 text-xs font-medium rounded-lg transition-colors ${
                    canAct
                      ? "text-white bg-red-600 hover:bg-red-700"
                      : "text-admin-faint bg-admin-raised cursor-not-allowed"
                  }`}
                >
                  Delete Experiment
                </button>
              </div>
            </>
          )}

          {feedback && (
            <p className={`text-xs rounded px-3 py-1.5 ${
              feedback.ok ? "text-admin-pastel-green-text bg-admin-pastel-green" : "text-admin-danger-text bg-admin-danger-soft"
            }`}>
              {feedback.msg}
            </p>
          )}
        </div>
      </div>

      {/* Confirmation modals */}
      {confirming === "reset_sessions" && matchedExperiment && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-admin-surface rounded-lg shadow-xl w-full max-w-sm mx-4 overflow-hidden border border-admin-border">
            <div className="px-5 pt-5 pb-3">
              <h3 className="text-sm font-semibold text-admin-text">
                Reset sessions for &ldquo;{matchedExperiment.experiment_id}&rdquo;?
              </h3>
              <p className="text-xs text-admin-muted mt-2 leading-relaxed">
                This will permanently delete{" "}
                <strong>{matchedExperiment.sessions} session(s)</strong>,{" "}
                <strong>{matchedExperiment.messages} message(s)</strong>, and all associated events and agent blocks.
                Tokens will be freed for reuse.
              </p>
              <p className="text-xs text-admin-muted mt-2 leading-relaxed">
                The experiment configuration and token definitions will be <strong>preserved</strong>.
              </p>
            </div>
            <div className="flex border-t border-admin-border">
              <button
                onClick={() => setConfirming(null)}
                className="flex-1 py-2.5 text-xs font-medium text-admin-muted hover:bg-admin-raised transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleResetSessions}
                className="flex-1 py-2.5 text-xs font-medium text-admin-pastel-amber-text hover:bg-admin-pastel-amber transition-colors border-l border-admin-border"
              >
                Yes, reset sessions
              </button>
            </div>
          </div>
        </div>
      )}

      {confirming === "delete_experiment" && matchedExperiment && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-admin-surface rounded-lg shadow-xl w-full max-w-sm mx-4 overflow-hidden border border-admin-border">
            <div className="px-5 pt-5 pb-3">
              <h3 className="text-sm font-semibold text-admin-text">
                Delete experiment &ldquo;{matchedExperiment.experiment_id}&rdquo;?
              </h3>
              <p className="text-xs text-admin-muted mt-2 leading-relaxed">
                This will <strong>permanently delete the experiment</strong> along with{" "}
                <strong>{matchedExperiment.sessions} session(s)</strong>,{" "}
                <strong>{matchedExperiment.messages} message(s)</strong>,{" "}
                <strong>{matchedExperiment.tokens} token(s)</strong>, and all associated events and agent blocks.
                The experiment configuration will also be removed.
              </p>
            </div>
            <div className="flex border-t border-admin-border">
              <button
                onClick={() => setConfirming(null)}
                className="flex-1 py-2.5 text-xs font-medium text-admin-muted hover:bg-admin-raised transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleDeleteExperiment}
                className="flex-1 py-2.5 text-xs font-medium text-red-500 hover:bg-admin-danger-soft transition-colors border-l border-admin-border"
              >
                Yes, delete everything
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/* ── Shared small components ──────────────────────────────────────────────── */

type PastelColor = "green" | "pink" | "amber" | "purple"

const PASTEL_CLASSES: Record<PastelColor, string> = {
  green: "bg-admin-pastel-green border-admin-pastel-green-text/10",
  pink: "bg-admin-pastel-pink border-admin-pastel-pink-text/10",
  amber: "bg-admin-pastel-amber border-admin-pastel-amber-text/10",
  purple: "bg-admin-pastel-purple border-admin-pastel-purple-text/10",
}
const PASTEL_TEXT: Record<PastelColor, string> = {
  green: "text-admin-pastel-green-text",
  pink: "text-admin-pastel-pink-text",
  amber: "text-admin-pastel-amber-text",
  purple: "text-admin-pastel-purple-text",
}

function StatCard({ label, value, sub, pastel }: { label: string; value: string | number; sub?: string; pastel?: PastelColor }) {
  const bgClass = pastel ? PASTEL_CLASSES[pastel] : "bg-admin-surface border-admin-border"
  const valueClass = pastel ? PASTEL_TEXT[pastel] : "text-admin-text"
  return (
    <div className={`rounded-lg border p-3 ${bgClass}`}>
      <p className="text-[10px] font-medium text-admin-faint uppercase tracking-wider">{label}</p>
      <p className={`text-xl font-bold mt-0.5 ${valueClass}`}>{value}</p>
      {sub && <p className="text-[10px] text-admin-faint mt-0.5">{sub}</p>}
    </div>
  )
}

function ConfigRow({
  label,
  value,
  mono,
  span2,
}: {
  label: string
  value: string | number
  mono?: boolean
  span2?: boolean
}) {
  return (
    <div className={span2 ? "col-span-2" : ""}>
      <span className="text-admin-faint text-xs">{label}: </span>
      <span className={`text-xs text-admin-text ${mono ? "font-mono" : ""}`}>{value}</span>
    </div>
  )
}

function LLMRow({
  role,
  provider,
  model,
  temp,
  topP,
  maxTokens,
}: {
  role: string
  provider: string
  model: string
  temp: number
  topP: number
  maxTokens: number
}) {
  return (
    <div className="bg-admin-raised rounded px-3 py-1.5 flex flex-wrap items-center gap-x-4 gap-y-0.5 text-xs border border-admin-border">
      <span className="font-semibold text-admin-text w-20">{role}</span>
      <span className="font-mono text-admin-muted">{provider}/{model}</span>
      <span className="text-admin-faint">temp={temp}</span>
      <span className="text-admin-faint">top_p={topP}</span>
      <span className="text-admin-faint">max={maxTokens}</span>
    </div>
  )
}

function formatDuration(startedAt: string | null, endedAt: string | null): string {
  if (!startedAt) return "-"
  const start = new Date(startedAt).getTime()
  const end = endedAt ? new Date(endedAt).getTime() : Date.now()
  const mins = Math.floor((end - start) / 60000)
  const secs = Math.floor(((end - start) % 60000) / 1000)
  return `${mins}:${String(secs).padStart(2, "0")}`
}

function SessionTable({
  adminKey,
  experimentId,
  sessions,
  title,
  showEndReason,
}: {
  adminKey: string
  experimentId: string
  sessions: SessionSummary[]
  title: string
  showEndReason?: boolean
}) {
  const [downloadingSessionId, setDownloadingSessionId] = useState<string | null>(null)
  const [downloadError, setDownloadError] = useState("")

  if (sessions.length === 0) return null

  const handleDownloadSession = async (sessionId: string) => {
    setDownloadingSessionId(sessionId)
    setDownloadError("")
    try {
      await downloadSessionBundle(adminKey, sessionId, experimentId)
    } catch (err) {
      setDownloadError(err instanceof Error ? err.message : "Session export failed")
    } finally {
      setDownloadingSessionId(null)
    }
  }

  return (
    <div className="bg-admin-surface rounded-lg border border-admin-border overflow-hidden">
      <div className="px-3 py-2 border-b border-admin-border">
        <h4 className="text-xs font-semibold text-admin-muted">{title}</h4>
      </div>
      {downloadError && (
        <div className="px-3 py-2 border-b border-admin-border text-[11px] text-red-600">
          {downloadError}
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-[10px] text-admin-faint uppercase tracking-wider border-b border-admin-border">
              <th className="px-3 py-1.5">Session</th>
              <th className="px-3 py-1.5">Token</th>
              <th className="px-3 py-1.5">Group</th>
              <th className="px-3 py-1.5 text-right">Msgs</th>
              <th className="px-3 py-1.5 text-right">{showEndReason ? "End Reason" : "Duration"}</th>
              <th className="px-3 py-1.5 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((s) => (
              <tr key={s.session_id} className="border-b border-admin-border/50 last:border-0 hover:bg-admin-raised/50">
                <td className="px-3 py-1.5 font-mono text-admin-faint">{s.session_id.slice(0, 8)}&hellip;</td>
                <td className="px-3 py-1.5 font-mono text-admin-faint">{s.token}</td>
                <td className="px-3 py-1.5 font-mono text-admin-faint">{s.treatment_group}</td>
                <td className="px-3 py-1.5 text-right font-medium text-admin-text">{s.message_count}</td>
                <td className="px-3 py-1.5 text-right text-admin-muted">
                  {showEndReason ? (s.end_reason || "-") : formatDuration(s.started_at, s.ended_at)}
                </td>
                <td className="px-3 py-1.5 text-right">
                  <div className="inline-flex items-center gap-3">
                    <button
                      onClick={() => handleDownloadSession(s.session_id)}
                      disabled={downloadingSessionId === s.session_id}
                      className="text-admin-muted hover:text-admin-text font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {downloadingSessionId === s.session_id ? "JSON..." : "JSON"}
                    </button>
                    <a
                      href={`${API_BASE}/session/${s.session_id}/report`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-admin-accent hover:text-admin-accent-hover font-medium"
                    >
                      View
                    </a>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function TokenProgress({ stats }: { stats: TokenGroupStats[] }) {
  if (stats.length === 0) return null
  return (
    <div className="bg-admin-surface rounded-lg border border-admin-border p-4 space-y-3">
      <h4 className="text-xs font-semibold text-admin-muted">Token Usage by Group</h4>
      {stats.map((g) => {
        const pct = g.total > 0 ? (g.used / g.total) * 100 : 0
        return (
          <div key={g.group} className="space-y-0.5">
            <div className="flex justify-between text-[10px]">
              <span className="font-mono font-medium text-admin-muted">{g.group}</span>
              <span className="text-admin-faint">{g.used}/{g.total}</span>
            </div>
            <div className="w-full h-1.5 bg-admin-raised rounded-full overflow-hidden">
              <div
                className="h-full bg-admin-accent rounded-full transition-all duration-300"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}

/* ── Compliance tab ───────────────────────────────────────────────────────── */

function ComplianceBar({ pct, color }: { pct: number | null; color: string }) {
  if (pct === null) return <span className="text-admin-faint text-xs">—</span>
  return (
    <div className="flex items-center gap-2 min-w-[120px]">
      <div className="flex-1 h-2 bg-admin-raised rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-300 ${color}`} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
      <span className="text-xs font-mono text-admin-text w-10 text-right">{pct.toFixed(1)}%</span>
    </div>
  )
}

function ComplianceTab({ adminKey, experimentId }: { adminKey: string; experimentId: string }) {
  const [groups, setGroups] = useState<ComplianceGroupStats[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = async (showLoading: boolean) => {
      if (showLoading) {
        setLoading(true)
        setError(null)
      }
      try {
        const res = await getComplianceStats(adminKey, experimentId)
        if (!cancelled) {
          setGroups(res.groups)
          if (showLoading) setLoading(false)
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load compliance stats")
          setGroups([])
          if (showLoading) setLoading(false)
        }
      }
    }

    setGroups([])
    setLoading(true)
    setError(null)
    void load(true)
    const iv = setInterval(() => {
      void load(false)
    }, 15000)
    return () => { cancelled = true; clearInterval(iv) }
  }, [adminKey, experimentId])

  if (loading) return <p className="text-sm text-admin-muted py-8 text-center">Loading compliance data…</p>
  if (error) return <p className="text-sm text-admin-danger-text py-8 text-center">Error: {error}</p>
  if (groups.length === 0) return (
    <div className="text-center py-12">
      <p className="text-sm text-admin-faint">No session data yet. Compliance statistics will appear here once sessions have messages classified.</p>
    </div>
  )

  const totalSessions = groups.reduce((s, g) => s + g.session_count, 0)
  const totalClassified = groups.reduce((s, g) => s + g.classified_count, 0)
  const totalIncivil = groups.reduce((s, g) => s + g.incivil_count, 0)
  const totalStanceClassified = groups.reduce((s, g) => s + g.stance_classified_count, 0)
  const totalLikeMinded = groups.reduce((s, g) => s + g.like_minded_count, 0)

  return (
    <div className="space-y-6">
      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Total Sessions" value={totalSessions} />
        <StatCard label="Classified Messages" value={totalClassified} sub="agent messages with civility label" />
        <StatCard
          label="Overall Incivility"
          value={totalClassified > 0 ? `${((totalIncivil / totalClassified) * 100).toFixed(1)}%` : "—"}
          pastel={totalClassified > 0 && (totalIncivil / totalClassified) > 0.6 ? "pink" : "green"}
        />
        <StatCard
          label="Overall Like-mindedness"
          value={totalStanceClassified > 0 ? `${((totalLikeMinded / totalStanceClassified) * 100).toFixed(1)}%` : "—"}
          pastel="purple"
        />
      </div>

      {/* Per-group table */}
      <div className="bg-admin-surface rounded-lg border border-admin-border overflow-hidden">
        <div className="px-5 py-3 border-b border-admin-border">
          <h3 className="text-sm font-semibold text-admin-text">Treatment Fidelity by Group</h3>
          <p className="text-xs text-admin-muted mt-0.5">
            Shows actual incivility and like-mindedness rates across all agent messages in completed/active sessions.
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-[10px] text-admin-faint uppercase tracking-wider border-b border-admin-border bg-admin-raised">
                <th className="px-4 py-2">Group</th>
                <th className="px-4 py-2 text-right">Sessions</th>
                <th className="px-4 py-2 text-right">Agent Msgs</th>
                <th className="px-4 py-2">Incivility Rate</th>
                <th className="px-4 py-2">Like-mindedness Rate</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => (
                <tr key={g.group} className="border-b border-admin-border/50 last:border-0 hover:bg-admin-raised/30">
                  <td className="px-4 py-2.5 font-mono font-medium text-admin-text">{g.group}</td>
                  <td className="px-4 py-2.5 text-right text-admin-muted">{g.session_count}</td>
                  <td className="px-4 py-2.5 text-right text-admin-muted">
                    {g.classified_count}
                    {g.classified_count !== g.stance_classified_count && (
                      <span className="text-admin-faint"> / {g.stance_classified_count} stance</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    <ComplianceBar
                      pct={g.incivil_pct}
                      color={g.incivil_pct !== null && g.incivil_pct > 50 ? "bg-admin-pastel-pink-text/60" : "bg-admin-pastel-green-text/60"}
                    />
                  </td>
                  <td className="px-4 py-2.5">
                    <ComplianceBar pct={g.like_minded_pct} color="bg-admin-pastel-purple-text/60" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <p className="text-[10px] text-admin-faint">
        Refreshes every 15 seconds. Incivility and like-mindedness rates are computed from agent messages only (participant messages are excluded). Like-mindedness denominator excludes messages where participant stance could not be inferred.
      </p>
    </div>
  )
}

/* ── Main Dashboard ───────────────────────────────────────────────────────── */

export default function Dashboard({ adminKey, onOpenWizard, onEditExperiment, onDuplicateExperiment, saveBanner, onDismissBanner, theme, onToggleTheme }: DashboardProps) {
  const [experiments, setExperiments] = useState<ExperimentSummary[]>([])
  const [selectedExperimentId, setSelectedExperimentId] = useState("")
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [tokenStats, setTokenStats] = useState<TokenGroupStats[]>([])
  const [loading, setLoading] = useState(true)
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null)
  const [activeTab, setActiveTab] = useState<Tab>("overview")

  const checkHealth = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/health`)
      setBackendOnline(res.ok)
    } catch {
      setBackendOnline(false)
    }
  }, [])

  const refreshExperiments = useCallback(async () => {
    try {
      const res = await listExperiments(adminKey)
      setExperiments(res.experiments)
      setSelectedExperimentId((prev) => {
        if (prev && res.experiments.some((e) => e.experiment_id === prev)) return prev
        return res.active_experiment_id || (res.experiments[0]?.experiment_id ?? "")
      })
      setBackendOnline(true)
    } catch {
      setExperiments([])
      setBackendOnline(false)
    }
  }, [adminKey])

  const refreshSessionData = useCallback(async () => {
    if (!selectedExperimentId) {
      setSessions([])
      setTokenStats([])
      return
    }
    try {
      const [sessRes, tokRes] = await Promise.all([
        listSessions(adminKey, selectedExperimentId),
        getTokenStats(adminKey, selectedExperimentId),
      ])
      setSessions(sessRes.sessions)
      setTokenStats(tokRes.groups)
    } catch {
      // silently fail
    }
  }, [adminKey, selectedExperimentId])

  const refresh = useCallback(async () => {
    await refreshExperiments()
    setLoading(false)
  }, [refreshExperiments])

  useEffect(() => {
    checkHealth()
    refresh()
    const interval = setInterval(() => { checkHealth(); refresh() }, 15000)
    return () => clearInterval(interval)
  }, [checkHealth, refresh])

  useEffect(() => {
    refreshSessionData()
    const interval = setInterval(refreshSessionData, 10000)
    return () => clearInterval(interval)
  }, [refreshSessionData])

  const handleSelect = async (id: string) => {
    setSelectedExperimentId(id)
    try { await activateExperiment(adminKey, id) } catch { /* ignore */ }
  }

  const noExperiments = experiments.length === 0 && !loading
  const activeSessionCount = sessions.filter((s) => s.status === "active").length

  return (
    <div className="min-h-dvh bg-admin-bg">
      {/* Top bar */}
      <TopBar
        experiments={experiments}
        selectedId={selectedExperimentId}
        onSelect={handleSelect}
        backendOnline={backendOnline}
        onOpenWizard={onOpenWizard}
        saveBanner={saveBanner}
        onDismissBanner={onDismissBanner}
        theme={theme}
        onToggleTheme={onToggleTheme}
      />

      {loading ? (
        <div className="max-w-6xl mx-auto px-6 py-12">
          <p className="text-admin-muted text-sm">Loading dashboard...</p>
        </div>
      ) : noExperiments ? (
        <div className="max-w-6xl mx-auto px-6">
          <div className="text-center py-16 space-y-4">
            <h2 className="text-xl font-semibold text-admin-text">No experiments yet</h2>
            <p className="text-sm text-admin-muted max-w-md mx-auto">
              Create your first experiment using the setup wizard. The wizard will guide you through
              configuring session settings, LLM models, treatment groups, and participant tokens.
            </p>
            <button
              onClick={onOpenWizard}
              className="px-6 py-3 text-sm font-medium bg-admin-accent text-white rounded-lg hover:bg-admin-accent-hover transition-colors"
            >
              Create First Experiment
            </button>
          </div>
        </div>
      ) : (
        <>
          {/* Tab bar */}
          <TabBar
            activeTab={activeTab}
            onTabChange={setActiveTab}
            sessionCount={activeSessionCount}
            errorCount={0}
          />

          {/* Tab content */}
          <div className="max-w-6xl mx-auto px-6 py-6">
            {!selectedExperimentId ? (
              <div className="text-center py-12">
                <p className="text-sm text-admin-faint">Select an experiment to view its data.</p>
              </div>
            ) : (
              <>
                {activeTab === "overview" && (
                  <OverviewTab
                    adminKey={adminKey}
                    experimentId={selectedExperimentId}
                    sessions={sessions}
                    tokenStats={tokenStats}
                    onEditExperiment={onEditExperiment}
                    onDuplicateExperiment={onDuplicateExperiment}
                  />
                )}
                {activeTab === "sessions" && (
                  <SessionsTab adminKey={adminKey} experimentId={selectedExperimentId} sessions={sessions} />
                )}
                {activeTab === "evaluate" && (
                  <EvaluateTab
                    key={selectedExperimentId}
                    adminKey={adminKey}
                    experimentId={selectedExperimentId}
                    sessions={sessions}
                  />
                )}
                {activeTab === "compliance" && (
                  <ComplianceTab
                    key={selectedExperimentId}
                    adminKey={adminKey}
                    experimentId={selectedExperimentId}
                  />
                )}
                {activeTab === "logs" && (
                  <EventLogTab
                    adminKey={adminKey}
                    experimentId={selectedExperimentId}
                    theme={theme}
                  />
                )}
                {activeTab === "settings" && (
                  <SettingsTab
                    adminKey={adminKey}
                    experiments={experiments}
                    selectedExperimentId={selectedExperimentId}
                    onRefresh={refresh}
                  />
                )}
              </>
            )}
          </div>
        </>
      )}
    </div>
  )
}
