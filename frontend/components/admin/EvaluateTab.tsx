"use client"

import { useEffect, useMemo, useState } from "react"
import { getExperimentConfig, getSessionMessagesForEvaluation, type SessionMessageForEvaluation } from "../../lib/admin-api"
import type { ExperimentalConfig, SessionSummary, SimulationConfig, TreatmentGroup } from "../../lib/admin-types"

type Alignment = "like_minded" | "not_like_minded" | ""
type HumanLike = "yes" | "no" | ""

type AnnotationRow = {
  message_id: string
  sender: string
  message: string
  incivility: boolean
  hate_speech: boolean
  threats_to_dem_freedom: boolean
  impoliteness: boolean
  alignment: Alignment
  human_like: HumanLike
  other: string
}

type ExperimentMeta = {
  description: string
  simulation: SimulationConfig
  experimental: ExperimentalConfig
}

const tableInputClass =
  "border border-admin-border rounded px-2 py-1 bg-admin-surface text-admin-text"

function csvEscape(value: string): string {
  if (value.includes(",") || value.includes('"') || value.includes("\n")) {
    return `"${value.replace(/"/g, '""')}"`
  }
  return value
}

function pct(value: number, total: number): string {
  return total > 0 ? `${((value / total) * 100).toFixed(1)}%` : ""
}

function formatModelsUsed(simulation: SimulationConfig | null): string {
  if (!simulation) return ""
  const rows = [
    `Dir:${simulation.director_llm_provider}/${simulation.director_llm_model}`,
    `Perf:${simulation.performer_llm_provider}/${simulation.performer_llm_model}`,
    `Mod:${simulation.moderator_llm_provider}/${simulation.moderator_llm_model}`,
    `Cls:${simulation.classifier_llm_provider}/${simulation.classifier_llm_model}`,
  ]
  return rows.join("\n")
}

function formatConfiguration(simulation: SimulationConfig | null): string {
  if (!simulation) return ""
  const rows = [
    `duration: ${simulation.session_duration_minutes}`,
    `seed: ${simulation.random_seed}`,
    `msg_min: ${simulation.messages_per_minute}`,
    `eval_int: ${simulation.evaluate_interval}`,
    `action_win: ${simulation.action_window_size}`,
    `perf_mem: ${simulation.performer_memory_size}`,
  ]
  return rows.join("\n")
}

function getSelectedGroup(
  experimental: ExperimentalConfig | null,
  treatmentGroup: string,
): TreatmentGroup | null {
  if (!experimental) return null
  return experimental.groups[treatmentGroup] || null
}

function getSeedArticleType(group: TreatmentGroup | null): string {
  const templateId = group?.seed?.template_id?.trim()
  if (templateId) return templateId
  if (group?.seed?.headline?.trim()) return "custom"
  return ""
}

function getIncivilityTypes(rows: AnnotationRow[]): string {
  const types: string[] = []
  if (rows.some((row) => row.impoliteness)) types.push("Impoliteness")
  if (rows.some((row) => row.hate_speech)) types.push("Hate Speech")
  if (rows.some((row) => row.threats_to_dem_freedom)) types.push("Threats to Democratic Freedoms")
  return types.join("; ")
}

function getNotes(rows: AnnotationRow[]): string {
  return rows
    .map((row) => row.other.trim())
    .filter(Boolean)
    .join(" | ")
}

function downloadCsv(lines: string[][], filename: string) {
  const csv = lines.map((line) => line.map((value) => csvEscape(value)).join(",")).join("\n")
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" })
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

export default function EvaluateTab({
  adminKey,
  experimentId,
  sessions,
}: {
  adminKey: string
  experimentId: string
  sessions: SessionSummary[]
}) {
  const endedSessions = useMemo(
    () => sessions.filter((s) => s.status === "ended" || s.status === "crashed"),
    [sessions],
  )
  const [selectedSessionId, setSelectedSessionId] = useState("")
  const [rows, setRows] = useState<AnnotationRow[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [experimentMeta, setExperimentMeta] = useState<ExperimentMeta | null>(null)

  const selectedSession = useMemo(
    () => endedSessions.find((session) => session.session_id === selectedSessionId) || null,
    [endedSessions, selectedSessionId],
  )

  const selectedGroup = useMemo(
    () => getSelectedGroup(experimentMeta?.experimental || null, selectedSession?.treatment_group || ""),
    [experimentMeta, selectedSession],
  )

  const evaluatedAgentRows = useMemo(
    () => rows.filter((row) => row.sender !== "participant" && row.sender !== "[news]"),
    [rows],
  )

  const participantMessagesCount = useMemo(
    () => rows.filter((row) => row.sender === "participant").length,
    [rows],
  )

  useEffect(() => {
    if (!selectedSessionId && endedSessions.length > 0) {
      setSelectedSessionId(endedSessions[0].session_id)
    }
  }, [endedSessions, selectedSessionId])

  useEffect(() => {
    let cancelled = false

    getExperimentConfig(adminKey, experimentId)
      .then((res) => {
        if (cancelled) return
        setExperimentMeta({
          description: res.description || "",
          simulation: res.config.simulation,
          experimental: res.config.experimental,
        })
      })
      .catch(() => {
        if (!cancelled) {
          setExperimentMeta(null)
        }
      })

    return () => {
      cancelled = true
    }
  }, [adminKey, experimentId])

  useEffect(() => {
    if (!selectedSessionId) {
      setRows([])
      return
    }

    let cancelled = false
    setLoading(true)
    setError("")

    getSessionMessagesForEvaluation(adminKey, selectedSessionId, experimentId)
      .then((res: { messages: SessionMessageForEvaluation[] }) => {
        if (cancelled) return
        setRows(
          res.messages.map((message) => ({
            message_id: message.message_id,
            sender: message.sender,
            message: message.content,
            incivility: false,
            hate_speech: false,
            threats_to_dem_freedom: false,
            impoliteness: false,
            alignment: "",
            human_like: "",
            other: "",
          })),
        )
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load session messages")
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [adminKey, experimentId, selectedSessionId])

  const setRow = (messageId: string, patch: Partial<AnnotationRow>) => {
    setRows((prev) => prev.map((row) => (row.message_id === messageId ? { ...row, ...patch } : row)))
  }

  const handleDownloadCSV = () => {
    const header = [
      "message",
      "incivility",
      "hate_speech",
      "threats_to_dem_freedom",
      "impoliteness",
      "alignment",
      "human_like",
      "other",
    ]
    const body = rows.map((row) => [
      row.message,
      row.incivility ? "1" : "0",
      row.hate_speech ? "1" : "0",
      row.threats_to_dem_freedom ? "1" : "0",
      row.impoliteness ? "1" : "0",
      row.alignment,
      row.human_like,
      row.other,
    ])
    downloadCsv([header, ...body], `${selectedSessionId || "session"}_evaluation.csv`)
  }

  const handleDownloadSummaryCSV = () => {
    const totalAgentMessages = evaluatedAgentRows.length
    const alignedRows = evaluatedAgentRows.filter((row) => row.alignment !== "")
    const likeMindedCount = alignedRows.filter((row) => row.alignment === "like_minded").length
    const notLikeMindedCount = alignedRows.filter((row) => row.alignment === "not_like_minded").length
    const incivilityCount = evaluatedAgentRows.filter((row) => row.incivility).length
    const impolitenessCount = evaluatedAgentRows.filter((row) => row.impoliteness).length
    const hateSpeechCount = evaluatedAgentRows.filter((row) => row.hate_speech).length
    const threatsCount = evaluatedAgentRows.filter((row) => row.threats_to_dem_freedom).length

    const modelsUsed = formatModelsUsed(experimentMeta?.simulation || null)
    const configuration = formatConfiguration(experimentMeta?.simulation || null)
    const seedArticleType = getSeedArticleType(selectedGroup)

    const groupHeader = [
      "RUN",
      "",
      "",
      "LLM_PIPELINE",
      "",
      "EXPERIMENT",
      "",
      "CONTEXT_DETAILS",
      "",
      "",
      "TREATMENT",
      "TEST_OUTPUTS",
      "",
      "",
      "",
      "",
      "",
      "",
      "NOTES",
      "INPUTS",
    ]

    const header = [
      "token_used",
      "experiment_name",
      "experiment_description",
      "models_used",
      "configuration",
      "n_agents",
      "seed_article_type",
      "chatroom_context",
      "ecological_validity",
      "incivility_framework",
      "treatment_group",
      "n_messages",
      "perc_incivil_messages",
      "perc_like_minded",
      "perc_not_like_minded",
      "perc_impoliteness",
      "perc_hate_speech",
      "perc_threats_to_democracy",
      "notes",
      "sent_messages",
    ]

    const row = [
      selectedSession?.token || "",
      experimentId,
      experimentMeta?.description || "",
      modelsUsed,
      configuration,
      String(experimentMeta?.simulation?.num_agents || ""),
      seedArticleType,
      experimentMeta?.experimental?.chatroom_context || "",
      experimentMeta?.experimental?.ecological_validity_criteria || "",
      experimentMeta?.experimental?.incivility_framework || "",
      selectedSession?.treatment_group || "",
      String(totalAgentMessages),
      pct(incivilityCount, totalAgentMessages),
      pct(likeMindedCount, alignedRows.length),
      pct(notLikeMindedCount, alignedRows.length),
      pct(impolitenessCount, totalAgentMessages),
      pct(hateSpeechCount, totalAgentMessages),
      pct(threatsCount, totalAgentMessages),
      getNotes(rows),
      String(participantMessagesCount),
    ]

    downloadCsv(
      [groupHeader, header, row.map((value, index) => (header[index] === "notes" ? `${value}${value && getIncivilityTypes(evaluatedAgentRows) ? " | " : ""}${getIncivilityTypes(evaluatedAgentRows) ? `Incivility types: ${getIncivilityTypes(evaluatedAgentRows)}` : ""}` : value))],
      `${selectedSessionId || "session"}_summary.csv`,
    )
  }

  return (
    <div className="space-y-4">
      <div className="bg-admin-surface rounded-lg border border-admin-border px-4 py-3 flex items-center gap-3 flex-wrap">
        <label className="text-xs font-medium text-admin-faint uppercase tracking-wider">Session</label>
        <select
          value={selectedSessionId}
          onChange={(e) => setSelectedSessionId(e.target.value)}
          className="text-xs font-mono border border-admin-border rounded-lg px-3 py-1.5 bg-admin-surface text-admin-text"
        >
          {endedSessions.length === 0 ? (
            <option value="">No completed sessions</option>
          ) : (
            endedSessions.map((session) => (
              <option key={session.session_id} value={session.session_id}>
                {session.session_id.slice(0, 8)}... ({session.treatment_group})
              </option>
            ))
          )}
        </select>
        <div className="flex-1" />
        <button
          onClick={handleDownloadCSV}
          disabled={rows.length === 0}
          className="px-3 py-1.5 text-xs font-medium bg-admin-accent text-white rounded-lg hover:bg-admin-accent-hover disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Download evaluation CSV
        </button>
        <button
          onClick={handleDownloadSummaryCSV}
          disabled={rows.length === 0}
          className="px-3 py-1.5 text-xs font-medium border border-admin-border text-admin-text rounded-lg hover:bg-admin-border/30 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Download summary CSV
        </button>
      </div>

      {loading ? (
        <div className="bg-admin-surface rounded-lg border border-admin-border p-4 text-sm text-admin-faint">
          Loading messages...
        </div>
      ) : error ? (
        <div className="bg-admin-surface rounded-lg border border-admin-border p-4 text-sm text-red-600">
          {error}
        </div>
      ) : rows.length === 0 ? (
        <div className="bg-admin-surface rounded-lg border border-admin-border p-4 text-sm text-admin-faint">
          No messages available for evaluation.
        </div>
      ) : (
        <div className="bg-admin-surface rounded-lg border border-admin-border overflow-x-auto">
          <table className="w-full text-xs min-w-[1250px]">
            <thead>
              <tr className="text-left text-[10px] text-admin-faint uppercase tracking-wider border-b border-admin-border">
                <th className="sticky top-0 z-10 px-3 py-3 bg-admin-surface">Sender</th>
                <th className="sticky top-0 z-10 px-3 py-3 bg-admin-surface min-w-[420px]">Message</th>
                <th className="sticky top-0 z-10 px-3 py-3 bg-red-50 text-center min-w-[90px]">Incivility</th>
                <th className="sticky top-0 z-10 px-3 py-3 bg-red-50 text-center min-w-[110px]">Hate Speech</th>
                <th className="sticky top-0 z-10 px-3 py-3 bg-red-50 text-center min-w-[110px]">Threats</th>
                <th className="sticky top-0 z-10 px-3 py-3 bg-red-50 text-center min-w-[110px]">Impoliteness</th>
                <th className="sticky top-0 z-10 px-3 py-3 bg-blue-50 min-w-[140px]">Alignment</th>
                <th className="sticky top-0 z-10 px-3 py-3 bg-emerald-50 min-w-[120px]">Human Like</th>
                <th className="sticky top-0 z-10 px-3 py-3 bg-amber-50 min-w-[220px]">Other</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.message_id}
                  className="border-b border-admin-border/50 align-top odd:bg-admin-surface even:bg-admin-border/10"
                >
                  <td className="px-3 py-3 font-mono text-admin-faint whitespace-nowrap">
                    <span
                      className={`inline-flex rounded-full px-2 py-1 text-[10px] font-semibold ${
                        row.sender === "participant"
                          ? "bg-blue-100 text-blue-700"
                          : row.sender === "[news]"
                            ? "bg-amber-100 text-amber-700"
                            : "bg-slate-100 text-slate-700"
                      }`}
                    >
                      {row.sender}
                    </span>
                  </td>
                  <td className="px-3 py-3 text-admin-text max-w-[500px] whitespace-pre-wrap leading-5">
                    {row.message}
                  </td>
                  <td className="px-3 py-3 text-center bg-red-50/60">
                    <input
                      type="checkbox"
                      checked={row.incivility}
                      onChange={(e) => setRow(row.message_id, { incivility: e.target.checked })}
                      className="h-4 w-4 accent-red-600"
                    />
                  </td>
                  <td className="px-3 py-3 text-center bg-red-50/60">
                    <input
                      type="checkbox"
                      checked={row.hate_speech}
                      onChange={(e) => setRow(row.message_id, { hate_speech: e.target.checked })}
                      className="h-4 w-4 accent-red-600"
                    />
                  </td>
                  <td className="px-3 py-3 text-center bg-red-50/60">
                    <input
                      type="checkbox"
                      checked={row.threats_to_dem_freedom}
                      onChange={(e) => setRow(row.message_id, { threats_to_dem_freedom: e.target.checked })}
                      className="h-4 w-4 accent-red-600"
                    />
                  </td>
                  <td className="px-3 py-3 text-center bg-red-50/60">
                    <input
                      type="checkbox"
                      checked={row.impoliteness}
                      onChange={(e) => setRow(row.message_id, { impoliteness: e.target.checked })}
                      className="h-4 w-4 accent-red-600"
                    />
                  </td>
                  <td className="px-3 py-3 bg-blue-50/60">
                    <select
                      value={row.alignment}
                      onChange={(e) => setRow(row.message_id, { alignment: e.target.value as Alignment })}
                      className={`${tableInputClass} min-w-[130px]`}
                    >
                      <option value="">-</option>
                      <option value="like_minded">like-minded</option>
                      <option value="not_like_minded">not-like-minded</option>
                    </select>
                  </td>
                  <td className="px-3 py-3 bg-emerald-50/60">
                    <select
                      value={row.human_like}
                      onChange={(e) => setRow(row.message_id, { human_like: e.target.value as HumanLike })}
                      className={`${tableInputClass} min-w-[100px]`}
                    >
                      <option value="">-</option>
                      <option value="yes">yes</option>
                      <option value="no">no</option>
                    </select>
                  </td>
                  <td className="px-3 py-3 bg-amber-50/60">
                    <input
                      type="text"
                      value={row.other}
                      onChange={(e) => setRow(row.message_id, { other: e.target.value })}
                      className="w-full border border-admin-border rounded px-2 py-1 bg-admin-surface text-admin-text"
                      placeholder="Notes"
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
