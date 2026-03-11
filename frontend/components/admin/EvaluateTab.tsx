"use client"

import { useEffect, useMemo, useState } from "react"
import { getSessionMessagesForEvaluation, type SessionMessageForEvaluation } from "../../lib/admin-api"
import type { SessionSummary } from "../../lib/admin-types"

type Stance = "pro" | "anti" | "neutral" | ""

type AnnotationRow = {
  message_id: string
  sender: string
  message: string
  incivility: boolean
  hate_speech: boolean
  threats_to_dem_freedom: boolean
  impoliteness: boolean
  stance: Stance
  human_like: boolean
  other: string
}

function csvEscape(v: string): string {
  if (v.includes(",") || v.includes('"') || v.includes("\n")) {
    return `"${v.replace(/"/g, '""')}"`
  }
  return v
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
  const [selectedSessionId, setSelectedSessionId] = useState<string>("")
  const [rows, setRows] = useState<AnnotationRow[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

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
          res.messages.map((m) => ({
            message_id: m.message_id,
            sender: m.sender,
            message: m.content,
            incivility: false,
            hate_speech: false,
            threats_to_dem_freedom: false,
            impoliteness: false,
            stance: "",
            human_like: false,
            other: "",
          })),
        )
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load session messages")
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [adminKey, experimentId, selectedSessionId])

  const setRow = (messageId: string, patch: Partial<AnnotationRow>) => {
    setRows((prev) => prev.map((r) => (r.message_id === messageId ? { ...r, ...patch } : r)))
  }

  const handleDownloadCSV = () => {
    const header = [
      "message",
      "incivility",
      "hate_speech",
      "threats_to_dem_freedom",
      "impoliteness",
      "stance",
      "human_like",
      "other",
    ]
    const body = rows.map((r) => [
      r.message,
      r.incivility ? "1" : "0",
      r.hate_speech ? "1" : "0",
      r.threats_to_dem_freedom ? "1" : "0",
      r.impoliteness ? "1" : "0",
      r.stance,
      r.human_like ? "1" : "0",
      r.other,
    ])
    const csv = [header, ...body].map((line) => line.map((v) => csvEscape(v)).join(",")).join("\n")
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `${selectedSessionId || "session"}_evaluation.csv`
    a.click()
    URL.revokeObjectURL(url)
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
            endedSessions.map((s) => (
              <option key={s.session_id} value={s.session_id}>
                {s.session_id.slice(0, 8)}… ({s.treatment_group})
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
      </div>

      {loading ? (
        <div className="bg-admin-surface rounded-lg border border-admin-border p-4 text-sm text-admin-faint">Loading messages...</div>
      ) : error ? (
        <div className="bg-admin-surface rounded-lg border border-admin-border p-4 text-sm text-red-600">{error}</div>
      ) : rows.length === 0 ? (
        <div className="bg-admin-surface rounded-lg border border-admin-border p-4 text-sm text-admin-faint">No messages available for evaluation.</div>
      ) : (
        <div className="bg-admin-surface rounded-lg border border-admin-border overflow-x-auto">
          <table className="w-full text-xs min-w-[1200px]">
            <thead>
              <tr className="text-left text-[10px] text-admin-faint uppercase tracking-wider border-b border-admin-border">
                <th className="px-3 py-2">Sender</th>
                <th className="px-3 py-2">Message</th>
                <th className="px-3 py-2 text-center">Incivility</th>
                <th className="px-3 py-2 text-center">Hate Speech</th>
                <th className="px-3 py-2 text-center">Threats</th>
                <th className="px-3 py-2 text-center">Impoliteness</th>
                <th className="px-3 py-2">Stance</th>
                <th className="px-3 py-2 text-center">Human Like</th>
                <th className="px-3 py-2">Other</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.message_id} className="border-b border-admin-border/50 align-top">
                  <td className="px-3 py-2 font-mono text-admin-faint whitespace-nowrap">{r.sender}</td>
                  <td className="px-3 py-2 text-admin-text max-w-[500px] whitespace-pre-wrap">{r.message}</td>
                  <td className="px-3 py-2 text-center"><input type="checkbox" checked={r.incivility} onChange={(e) => setRow(r.message_id, { incivility: e.target.checked })} /></td>
                  <td className="px-3 py-2 text-center"><input type="checkbox" checked={r.hate_speech} onChange={(e) => setRow(r.message_id, { hate_speech: e.target.checked })} /></td>
                  <td className="px-3 py-2 text-center"><input type="checkbox" checked={r.threats_to_dem_freedom} onChange={(e) => setRow(r.message_id, { threats_to_dem_freedom: e.target.checked })} /></td>
                  <td className="px-3 py-2 text-center"><input type="checkbox" checked={r.impoliteness} onChange={(e) => setRow(r.message_id, { impoliteness: e.target.checked })} /></td>
                  <td className="px-3 py-2">
                    <select
                      value={r.stance}
                      onChange={(e) => setRow(r.message_id, { stance: e.target.value as Stance })}
                      className="border border-admin-border rounded px-2 py-1 bg-admin-surface text-admin-text"
                    >
                      <option value="">-</option>
                      <option value="pro">pro</option>
                      <option value="anti">anti</option>
                      <option value="neutral">neutral</option>
                    </select>
                  </td>
                  <td className="px-3 py-2 text-center"><input type="checkbox" checked={r.human_like} onChange={(e) => setRow(r.message_id, { human_like: e.target.checked })} /></td>
                  <td className="px-3 py-2">
                    <input
                      type="text"
                      value={r.other}
                      onChange={(e) => setRow(r.message_id, { other: e.target.value })}
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
