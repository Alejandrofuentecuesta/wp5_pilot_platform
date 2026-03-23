"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import {
  downloadEvaluationSummaryCSV,
  getSessionMessagesForEvaluation,
  saveSessionEvaluation,
  type SessionMessageForEvaluation,
} from "../../lib/admin-api"
import type { SessionSummary } from "../../lib/admin-types"

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

const tableInputClass =
  "border border-admin-border rounded px-2 py-1 bg-admin-surface text-admin-text"

function csvEscape(value: string): string {
  if (value.includes(",") || value.includes('"') || value.includes("\n")) {
    return `"${value.replace(/"/g, '""')}"`
  }
  return value
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
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle")
  const [summaryExporting, setSummaryExporting] = useState(false)
  const saveTimeoutRef = useRef<number | null>(null)
  const skipAutosaveRef = useRef(true)

  useEffect(() => {
    if (!selectedSessionId && endedSessions.length > 0) {
      setSelectedSessionId(endedSessions[0].session_id)
    }
  }, [endedSessions, selectedSessionId])

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
            incivility: message.manual_evaluation?.incivility ?? false,
            hate_speech: message.manual_evaluation?.hate_speech ?? false,
            threats_to_dem_freedom: message.manual_evaluation?.threats_to_dem_freedom ?? false,
            impoliteness: message.manual_evaluation?.impoliteness ?? false,
            alignment: (message.manual_evaluation?.alignment as Alignment | undefined) ?? "",
            human_like: (message.manual_evaluation?.human_like as HumanLike | undefined) ?? "",
            other: message.manual_evaluation?.other ?? "",
          })),
        )
        skipAutosaveRef.current = true
        setSaveStatus("idle")
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

  useEffect(() => {
    if (!selectedSessionId || rows.length === 0) return
    if (skipAutosaveRef.current) {
      skipAutosaveRef.current = false
      return
    }

    setSaveStatus("saving")
    if (saveTimeoutRef.current) {
      window.clearTimeout(saveTimeoutRef.current)
    }

    saveTimeoutRef.current = window.setTimeout(async () => {
      try {
        await saveSessionEvaluation(
          adminKey,
          selectedSessionId,
          experimentId,
          rows.map((row) => ({
            message_id: row.message_id,
            incivility: row.incivility,
            hate_speech: row.hate_speech,
            threats_to_dem_freedom: row.threats_to_dem_freedom,
            impoliteness: row.impoliteness,
            alignment: row.alignment,
            human_like: row.human_like,
            other: row.other,
          })),
        )
        setSaveStatus("saved")
      } catch (err) {
        console.error(err)
        setSaveStatus("error")
      }
    }, 500)

    return () => {
      if (saveTimeoutRef.current) {
        window.clearTimeout(saveTimeoutRef.current)
      }
    }
  }, [adminKey, experimentId, rows, selectedSessionId])

  const setRow = (messageId: string, patch: Partial<AnnotationRow>) => {
    setRows((prev) => prev.map((row) => (row.message_id === messageId ? { ...row, ...patch } : row)))
  }

  const flushPendingSave = async () => {
    if (!selectedSessionId || rows.length === 0) return
    if (saveTimeoutRef.current) {
      window.clearTimeout(saveTimeoutRef.current)
      saveTimeoutRef.current = null
    }

    setSaveStatus("saving")
    try {
      await saveSessionEvaluation(
        adminKey,
        selectedSessionId,
        experimentId,
        rows.map((row) => ({
          message_id: row.message_id,
          incivility: row.incivility,
          hate_speech: row.hate_speech,
          threats_to_dem_freedom: row.threats_to_dem_freedom,
          impoliteness: row.impoliteness,
          alignment: row.alignment,
          human_like: row.human_like,
          other: row.other,
        })),
      )
      setSaveStatus("saved")
    } catch (err) {
      console.error(err)
      setSaveStatus("error")
      throw err
    }
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

  const handleDownloadSummaryCSV = async () => {
    try {
      await flushPendingSave()
      setSummaryExporting(true)
      setError("")
      await downloadEvaluationSummaryCSV(adminKey, experimentId)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to download summary CSV")
    } finally {
      setSummaryExporting(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="bg-admin-surface rounded-lg border border-admin-border px-4 py-3 flex items-center gap-3 flex-wrap">
        <label className="text-xs font-medium text-admin-faint uppercase tracking-wider">Session</label>
        <select
          value={selectedSessionId}
          onChange={(e) => {
            void flushPendingSave()
            setSelectedSessionId(e.target.value)
          }}
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
        <span className="text-xs text-admin-faint">
          {saveStatus === "saving" && "Saving…"}
          {saveStatus === "saved" && "Saved"}
          {saveStatus === "error" && "Save failed"}
        </span>
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
          disabled={summaryExporting || endedSessions.length === 0}
          className="px-3 py-1.5 text-xs font-medium border border-admin-border text-admin-text rounded-lg hover:bg-admin-border/30 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {summaryExporting ? "Exporting..." : "Download summary CSV"}
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
