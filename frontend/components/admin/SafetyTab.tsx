"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  getSafetyPolicy,
  getSafetySummary,
  downloadReviewedSafetyFlags,
  listSafetyFlags,
  reviewSafetyFlag,
  safetySessionAction,
  testSafetyClassifier,
} from "../../lib/admin-api"
import type { SafetyClassifierTestResult } from "../../lib/admin-api"
import type { SafetyFlag, SafetyPolicy, SafetySummary } from "../../lib/admin-types"

/* The Safety tab is the human-review side of the safety screen. Every flag
   the screen opens (an `unsafe` verdict on an agent or participant message,
   or a turn withheld because no verdict could be obtained) stays in the open
   queue until a named reviewer records a decision. Session controls act on
   the live session behind the flag. */

const POLL_MS = 5000
const REVIEWER_KEY = "wp5-safety-reviewer"

type View = "open" | "reviewed"

function fmtElapsed(ms: number): string {
  if (ms < 0) ms = 0
  const s = Math.floor(ms / 1000)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`
  return `${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`
}

function fmtTime(iso: string | null): string {
  if (!iso) return "—"
  const d = new Date(iso)
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
}

function shortId(id: string): string {
  return id.slice(0, 8)
}

function useNow(tickMs = 1000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), tickMs)
    return () => window.clearInterval(t)
  }, [tickMs])
  return now
}

function playChime() {
  try {
    const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
    const ctx = new Ctx()
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.frequency.value = 880
    gain.gain.value = 0.08
    osc.connect(gain)
    gain.connect(ctx.destination)
    osc.start()
    osc.stop(ctx.currentTime + 0.25)
  } catch {
    /* audio blocked until first interaction; the badge still updates */
  }
}

/* ── Reviewer identity ────────────────────────────────────────────────── */

function ReviewerBar({ reviewer, onChange }: { reviewer: string; onChange: (v: string) => void }) {
  const [draft, setDraft] = useState(reviewer)
  const [editing, setEditing] = useState(!reviewer)
  if (!editing) {
    return (
      <div className="flex items-center gap-2 text-xs text-admin-muted">
        Reviewing as <span className="font-medium text-admin-text">{reviewer}</span>
        <button className="underline text-admin-faint hover:text-admin-text" onClick={() => setEditing(true)}>
          change
        </button>
      </div>
    )
  }
  return (
    <form
      className="flex items-center gap-2 text-xs"
      onSubmit={(e) => {
        e.preventDefault()
        const v = draft.trim()
        if (!v) return
        onChange(v)
        setEditing(false)
      }}
    >
      <label className="text-admin-muted">Your name (recorded with every review):</label>
      <input
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        maxLength={80}
        className="border border-admin-border rounded px-2 py-1 bg-admin-surface text-admin-text"
        placeholder="e.g. Laia"
      />
      <button
        type="submit"
        className="px-2 py-1 rounded bg-admin-accent text-white disabled:opacity-40"
        disabled={!draft.trim()}
      >
        Save
      </button>
    </form>
  )
}

/* ── Summary strip ────────────────────────────────────────────────────── */

function Stat({ label, value, tone }: { label: string; value: string | number; tone?: "danger" | "warn" | "ok" }) {
  const toneClass =
    tone === "danger"
      ? "bg-admin-danger-soft text-admin-danger-text border-admin-danger-border"
      : tone === "warn"
        ? "bg-admin-pastel-amber text-admin-pastel-amber-text border-admin-border"
        : tone === "ok"
          ? "bg-admin-pastel-green text-admin-pastel-green-text border-admin-border"
          : "bg-admin-surface text-admin-text border-admin-border"
  return (
    <div className={`rounded-lg border px-3 py-2 ${toneClass}`}>
      <div className="text-[10px] uppercase tracking-wide opacity-70">{label}</div>
      <div className="text-lg font-semibold leading-tight">{value}</div>
    </div>
  )
}

function SummaryStrip({ summary, now }: { summary: SafetySummary | null; now: number }) {
  if (!summary) return null
  const lastVerdictAge = summary.last_verdict_at ? now - new Date(summary.last_verdict_at).getTime() : null
  const unscreenedLive = summary.experiments.filter((e) => e.live > 0 && !e.screening_enabled)
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Stat label="Open flags" value={summary.open_flags} tone={summary.open_flags > 0 ? "danger" : "ok"} />
        <Stat label="Live sessions" value={summary.live_sessions} />
        <Stat label="Paused by reviewer" value={summary.paused_sessions} tone={summary.paused_sessions > 0 ? "warn" : undefined} />
        <Stat
          label="No verdict (10 min)"
          value={summary.unavailable_last_10m}
          tone={summary.unavailable_last_10m > 0 ? "warn" : undefined}
        />
        <Stat
          label="Last verdict"
          value={lastVerdictAge === null ? "never" : `${fmtElapsed(lastVerdictAge)} ago`}
        />
      </div>
      {unscreenedLive.length > 0 && (
        <div className="rounded-lg border border-admin-danger-border bg-admin-danger-soft text-admin-danger-text px-3 py-2 text-xs">
          Screening is <strong>disabled</strong> for live experiment{unscreenedLive.length > 1 ? "s" : ""}{" "}
          {unscreenedLive.map((e) => e.experiment_id).join(", ")}. Messages in those sessions are not checked.
        </div>
      )}
    </div>
  )
}

/* ── Flag row ─────────────────────────────────────────────────────────── */

function CategoryChips({ flag }: { flag: SafetyFlag }) {
  if (flag.verdict === "unavailable") {
    return (
      <span
        title={flag.error || "no verdict"}
        className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-admin-pastel-amber text-admin-pastel-amber-text"
      >
        no verdict — turn withheld
      </span>
    )
  }
  return (
    <span className="inline-flex flex-wrap gap-1" title={flag.raw_output || ""}>
      {flag.categories.map((code, i) => (
        <span
          key={code}
          className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-admin-danger-soft text-admin-danger-text"
        >
          {code} {flag.category_names[i] || ""}
        </span>
      ))}
      {flag.unsafe_prob !== null && (
        <span className="text-[10px] text-admin-faint self-center">p={flag.unsafe_prob.toFixed(2)}</span>
      )}
    </span>
  )
}

function SessionBadge({ flag }: { flag: SafetyFlag }) {
  if (flag.safety_paused_at && flag.session_status === "active") {
    return <span className="text-[10px] px-1.5 py-0.5 rounded bg-admin-pastel-amber text-admin-pastel-amber-text">paused</span>
  }
  if (flag.session_status === "active") {
    return <span className="text-[10px] px-1.5 py-0.5 rounded bg-admin-pastel-green text-admin-pastel-green-text">live</span>
  }
  return <span className="text-[10px] px-1.5 py-0.5 rounded bg-admin-raised text-admin-muted">{flag.session_status}</span>
}

function FlagRow({
  flag,
  now,
  reviewer,
  busy,
  onReview,
  onSessionAction,
  onSelectSession,
}: {
  flag: SafetyFlag
  now: number
  reviewer: string
  busy: boolean
  onReview: (flag: SafetyFlag, verdict: "no_concern" | "concern", note: string) => void
  onSessionAction: (flag: SafetyFlag, action: "pause" | "resume" | "end") => void
  onSelectSession: (sessionId: string) => void
}) {
  const [note, setNote] = useState("")
  const [showContext, setShowContext] = useState(false)
  const isParticipant = flag.sender_type === "participant"
  const elapsed = flag.displayed_at ? now - new Date(flag.displayed_at).getTime() : null
  const autoConcernRemaining = Math.max(0, 120000 - (now - new Date(flag.created_at).getTime()))
  const paused = !!flag.safety_paused_at
  const canAct = flag.live && !!reviewer
  const canPublishWithheld =
    !isParticipant &&
    !flag.displayed_at &&
    flag.verdict === "unsafe"

  return (
    <div
      className={`rounded-lg border p-3 ${
        isParticipant
          ? "border-admin-pastel-purple bg-admin-pastel-purple/20 border-l-4"
          : "border-admin-border bg-admin-surface"
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-admin-faint">{fmtTime(flag.created_at)}</span>
          <span
            className={`font-mono font-semibold ${
              elapsed === null ? "text-admin-pastel-amber-text" : elapsed > 120000 ? "text-admin-danger-text" : "text-admin-text"
            }`}
            title={elapsed === null ? "Never shown to the participant" : "Time since the participant saw this"}
          >
            {elapsed === null
              ? `withheld · auto concern in ${fmtElapsed(autoConcernRemaining)}`
              : `seen ${fmtElapsed(elapsed)} ago`}
          </span>
          <button
            className="text-admin-accent hover:underline"
            onClick={() => onSelectSession(flag.session_id)}
            title={flag.session_id}
          >
            {flag.user_name} · {shortId(flag.session_id)}
          </button>
          <span className="text-admin-faint">{flag.treatment_group}</span>
          <span className="text-admin-faint">{flag.experiment_id}</span>
          <SessionBadge flag={flag} />
        </div>
        <div className="flex items-center gap-1">
          {paused ? (
            <button
              disabled={!canAct || busy}
              onClick={() => onSessionAction(flag, "resume")}
              className="px-2 py-1 rounded text-xs bg-admin-pastel-green text-admin-pastel-green-text disabled:opacity-40"
            >
              Resume
            </button>
          ) : (
            <button
              disabled={!canAct || busy}
              onClick={() => onSessionAction(flag, "pause")}
              className="px-2 py-1 rounded text-xs bg-admin-pastel-amber text-admin-pastel-amber-text disabled:opacity-40"
              title={flag.live ? "Freeze this participant's room" : "Session is not live"}
            >
              Pause
            </button>
          )}
          <button
            disabled={!canAct || busy}
            onClick={() => {
              if (window.confirm(`End session for ${flag.user_name}? The participant will be sent back to the panel as non-complete.`)) {
                onSessionAction(flag, "end")
              }
            }}
            className="px-2 py-1 rounded text-xs bg-admin-danger-soft text-admin-danger-text disabled:opacity-40"
          >
            End
          </button>
        </div>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <span
          className={`inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded ${
            isParticipant
              ? "bg-admin-pastel-purple text-admin-pastel-purple-text"
              : "bg-admin-raised text-admin-text"
          }`}
        >
          {isParticipant ? (
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
            </svg>
          ) : (
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 3v2m6-2v2M9 19v2m6-2v2M3 9h2m-2 6h2m14-6h2m-2 6h2M7 7h10v10H7z" />
            </svg>
          )}
          {isParticipant ? "PARTICIPANT" : `AGENT ${flag.sender}`}
        </span>
        <CategoryChips flag={flag} />
      </div>

      <p className="mt-2 text-sm text-admin-text whitespace-pre-wrap">{flag.content}</p>

      {flag.rationale && (
        <p className="mt-1 text-xs text-admin-muted italic">
          {flag.model ? <span className="not-italic font-medium">{flag.model}: </span> : null}
          &ldquo;{flag.rationale}&rdquo;
        </p>
      )}

      {(flag.context_user_turn || flag.reasoning) && (
        <div className="mt-1">
          <button className="text-[11px] text-admin-faint hover:text-admin-text underline" onClick={() => setShowContext((v) => !v)}>
            {showContext ? "hide" : "show"} what the classifier saw and its reasoning
          </button>
          {showContext && (
            <div className="mt-1 space-y-1 text-xs text-admin-muted border-l-2 border-admin-border pl-2">
              {flag.context_user_turn && <p className="whitespace-pre-wrap">{flag.context_user_turn}</p>}
              {flag.reasoning && (
                <p className="whitespace-pre-wrap italic">
                  <span className="not-italic font-medium">Reasoning: </span>
                  {flag.reasoning}
                </p>
              )}
              {flag.policy_version && <p className="text-[10px] text-admin-faint">policy {flag.policy_version}</p>}
            </div>
          )}
        </div>
      )}

      {flag.reviewed_at ? (
        <div className="mt-2 text-xs text-admin-muted">
          Reviewed {fmtTime(flag.reviewed_at)} by <span className="font-medium">{flag.reviewed_by}</span>:{" "}
          <span className={flag.review_verdict === "concern" ? "text-admin-danger-text font-medium" : "font-medium"}>
            {flag.review_verdict === "concern" ? "concern" : "no concern"}
          </span>
          {flag.review_note && <span> — {flag.review_note}</span>}
        </div>
      ) : (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="note (optional)"
            className="flex-1 min-w-[160px] border border-admin-border rounded px-2 py-1 text-xs bg-admin-bg text-admin-text"
          />
          <button
            disabled={!reviewer || busy || (canPublishWithheld && (!flag.live || paused))}
            onClick={() => onReview(flag, "no_concern", note)}
            className="px-3 py-1 rounded text-xs font-medium bg-admin-pastel-green text-admin-pastel-green-text disabled:opacity-40"
            title={
              !reviewer
                ? "Enter your name above first"
                : canPublishWithheld
                  ? "Approve and publish this withheld agent message"
                  : "Mark this flag as no concern"
            }
          >
            {canPublishWithheld ? "No concern & publish" : "No concern"}
          </button>
          <button
            disabled={!reviewer || busy}
            onClick={() => onReview(flag, "concern", note)}
            className="px-3 py-1 rounded text-xs font-medium bg-admin-danger-soft text-admin-danger-text disabled:opacity-40"
          >
            Concern
          </button>
        </div>
      )}
    </div>
  )
}

/* ── Screening policy panel ───────────────────────────────────────────── */

/* Which classifier screens messages is chosen in LLM Pipeline. The policy it
   applies is fixed in the backend (utils/safety/policies) and shown here
   read-only; replacing it is a code change, never an admin-panel edit. */
type ClassifierKey = "safeguard" | "claude"

const CLASSIFIER_OPTIONS: { key: ClassifierKey; label: string }[] = [
  { key: "safeguard", label: "gpt-oss-safeguard (Konstanz)" },
  { key: "claude", label: "Claude (Anthropic API)" },
]

function classifierKeyFor(transport: string | null): ClassifierKey {
  return transport === "anthropic_messages" ? "claude" : "safeguard"
}

/* Human label for whatever is actually saved, e.g. "Claude (claude-haiku-4-5-20251001)"
   or "gpt-oss-safeguard (Konstanz)" when no model override is saved. */
function classifierSummary(transport: string | null, model: string | null): string {
  const key = classifierKeyFor(transport)
  const base = CLASSIFIER_OPTIONS.find((o) => o.key === key)!.label
  return model ? `${base} (${model})` : base
}

function PolicyPanel({ adminKey, experimentId }: { adminKey: string; experimentId: string }) {
  const [policy, setPolicy] = useState<SafetyPolicy | null>(null)
  const [open, setOpen] = useState(false)
  const [showText, setShowText] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<SafetyClassifierTestResult | null>(null)

  const load = useCallback(async () => {
    try {
      setPolicy(await getSafetyPolicy(adminKey, experimentId))
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Failed to load policy")
    }
  }, [adminKey, experimentId])

  useEffect(() => {
    load()
  }, [load])

  if (!policy) return msg ? <p className="text-xs text-admin-danger-text">{msg}</p> : null

  const runTest = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      setTestResult(await testSafetyClassifier(adminKey, experimentId))
    } catch (e) {
      setTestResult({ ok: false, error: e instanceof Error ? e.message : "Test failed" })
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="rounded-lg border border-admin-border bg-admin-surface">
      <button
        className="w-full flex items-center justify-between px-4 py-3 text-left"
        onClick={() => setOpen((v) => !v)}
      >
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-admin-text">Screening policy</span>
          <span className="text-xs text-admin-muted">
            {experimentId} ·{" "}
            {policy.enabled
              ? `${classifierSummary(policy.transport, policy.model)} · policy ${policy.policy.version}`
              : "screening disabled"}
          </span>
          {policy.locked && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-admin-pastel-amber text-admin-pastel-amber-text">locked</span>
          )}
        </div>
        <span className="text-xs text-admin-faint">{open ? "hide" : "show"}</span>
      </button>

      {open && (
        <div className="px-4 pb-4 space-y-4 border-t border-admin-border pt-3">
          <div>
            <label className="block text-xs font-medium text-admin-text mb-1">Classifier model</label>
            <p className="text-xs text-admin-muted">
              <span className="font-medium text-admin-text">{classifierSummary(policy.transport, policy.model)}</span>
              {policy.enabled ? " is enabled." : " is disabled."} Configure the provider, model, endpoint, and timeout in LLM Pipeline.
            </p>

            <div className="mt-2">
              <button
                type="button"
                disabled={testing || !policy.enabled}
                onClick={runTest}
                className="rounded border border-admin-border bg-admin-bg px-3 py-1.5 text-xs font-medium text-admin-text shadow-sm hover:bg-admin-raised disabled:opacity-40"
              >
                {testing ? "Testing…" : "Test classifier"}
              </button>
              {!policy.enabled && <span className="ml-2 text-[11px] text-admin-faint">enable screening first</span>}

              {testResult && (
                <div
                  className={`mt-2 rounded border px-3 py-2 text-xs ${
                    testResult.ok
                      ? "border-admin-pastel-green bg-admin-pastel-green/20 text-admin-pastel-green-text"
                      : "border-admin-danger bg-admin-danger-soft/40 text-admin-danger-text"
                  }`}
                >
                  {testResult.error ? (
                    <p className="font-medium">{testResult.error}</p>
                  ) : (
                    <>
                      <p className="font-medium">
                        {testResult.status === "unavailable"
                          ? "No verdict — the classifier did not answer usably."
                          : `Verdict: ${testResult.status}${testResult.categories?.length ? ` (${testResult.categories.join(", ")})` : ""}`}
                        {typeof testResult.latency_ms === "number" && (
                          <span className="ml-2 font-normal text-admin-faint">{testResult.latency_ms}ms</span>
                        )}
                      </p>
                      {testResult.rationale && <p className="mt-1 italic">&ldquo;{testResult.rationale}&rdquo;</p>}
                    </>
                  )}
                  {(testResult.transport || testResult.model) && (
                    <p className="mt-1 text-admin-faint">
                      {testResult.transport} · {testResult.base_url} · {testResult.model}
                    </p>
                  )}
                </div>
              )}
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-admin-text mb-1">Policy</label>
            <p className="text-xs text-admin-muted">
              <span className="font-mono">{policy.policy.version}</span>. Every message is judged with the two messages
              before it, plus the participant&apos;s latest message and the quoted message when those fall outside that
              window. The policy is part of the code and cannot be edited here.
            </p>
            <button
              className="mt-1 text-[11px] text-admin-faint hover:text-admin-text underline"
              onClick={() => setShowText((v) => !v)}
            >
              {showText ? "hide" : "show"} the policy text
            </button>
            {showText && (
              <pre className="mt-1 max-h-96 overflow-auto whitespace-pre-wrap rounded border border-admin-border bg-admin-bg p-2 text-[11px] text-admin-muted">
                {policy.policy.text}
              </pre>
            )}
          </div>

          {policy.locked && (
            <p className="text-xs text-admin-pastel-amber-text">
              Screening settings for this experiment are locked for fieldwork.
            </p>
          )}
        </div>
      )}
    </div>
  )
}

/* ── Tab ──────────────────────────────────────────────────────────────── */

export default function SafetyTab({ adminKey }: { adminKey: string }) {
  const [reviewer, setReviewer] = useState("")
  const [view, setView] = useState<View>("open")
  const [sessionFilter, setSessionFilter] = useState<string | null>(null)
  const [flags, setFlags] = useState<SafetyFlag[]>([])
  const [summary, setSummary] = useState<SafetySummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [exportBusy, setExportBusy] = useState<"json" | "csv" | null>(null)
  const [clockOffset, setClockOffset] = useState(0)
  const knownOpen = useRef<Set<string> | null>(null)
  const now = useNow() + clockOffset

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(REVIEWER_KEY)
      if (stored) setReviewer(stored)
    } catch {
      /* private mode */
    }
  }, [])

  const saveReviewer = (v: string) => {
    setReviewer(v)
    try {
      window.localStorage.setItem(REVIEWER_KEY, v)
    } catch {
      /* ignore */
    }
  }

  const downloadReviewed = async (format: "json" | "csv") => {
    setExportBusy(format)
    try {
      const { blob, filename } = await downloadReviewedSafetyFlags(adminKey, format)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement("a")
      anchor.href = url
      anchor.download = filename
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to export reviewed flags")
    } finally {
      setExportBusy(null)
    }
  }

  const load = useCallback(async () => {
    try {
      const [sum, res] = await Promise.all([
        getSafetySummary(adminKey),
        listSafetyFlags(adminKey, {
          status: sessionFilter ? "all" : view,
          session_id: sessionFilter || undefined,
          limit: 300,
        }),
      ])
      setSummary(sum)
      setFlags(res.flags)
      // Elapsed counters use the server clock so a skewed laptop does not
      // misreport review latency.
      setClockOffset(new Date(res.server_time).getTime() - Date.now())
      setError(null)
      const openIds = new Set(res.flags.filter((f) => !f.reviewed_at).map((f) => f.flag_id))
      if (knownOpen.current !== null) {
        const fresh = [...openIds].some((id) => !knownOpen.current!.has(id))
        if (fresh) playChime()
      }
      knownOpen.current = openIds
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load")
    }
  }, [adminKey, view, sessionFilter])

  useEffect(() => {
    load()
    const t = window.setInterval(load, POLL_MS)
    return () => window.clearInterval(t)
  }, [load])

  const onReview = async (flag: SafetyFlag, verdict: "no_concern" | "concern", note: string) => {
    setBusyId(flag.flag_id)
    try {
      await reviewSafetyFlag(adminKey, flag.flag_id, verdict, reviewer, note)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : "Review failed")
    } finally {
      setBusyId(null)
    }
  }

  const onSessionAction = async (flag: SafetyFlag, action: "pause" | "resume" | "end") => {
    setBusyId(flag.flag_id)
    try {
      await safetySessionAction(adminKey, flag.session_id, action, reviewer)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : `${action} failed`)
    } finally {
      setBusyId(null)
    }
  }

  const grouped = useMemo(() => {
    if (!sessionFilter) return null
    return [...flags].sort((a, b) => a.created_at.localeCompare(b.created_at))
  }, [flags, sessionFilter])

  const openCount = summary?.open_flags ?? 0
  // The policy panel edits the live experiment (the one with sessions, else
  // the first screening-enabled one).
  const policyExperimentId = useMemo(() => {
    const exps = summary?.experiments ?? []
    return (exps.find((e) => e.live > 0) ?? exps.find((e) => e.screening_enabled) ?? exps[0])?.experiment_id ?? null
  }, [summary])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-admin-text">Safety monitor</h2>
          <p className="text-xs text-admin-muted">
            Withheld agent messages can be reviewed for 120 seconds. If no decision is recorded, they are marked as concern and remain out of the chat. Agent rows are grey; participant rows are purple.
          </p>
        </div>
        <ReviewerBar reviewer={reviewer} onChange={saveReviewer} />
      </div>

      <SummaryStrip summary={summary} now={now} />

      {policyExperimentId && <PolicyPanel adminKey={adminKey} experimentId={policyExperimentId} />}

      {error && (
        <div className="rounded border border-admin-danger-border bg-admin-danger-soft text-admin-danger-text px-3 py-2 text-xs">
          {error}
        </div>
      )}

      <div className="flex items-center gap-2 text-xs">
        {sessionFilter ? (
          <>
            <span className="text-admin-muted">
              Session <span className="font-mono">{shortId(sessionFilter)}</span> — all flags in order
            </span>
            <button className="underline text-admin-accent" onClick={() => setSessionFilter(null)}>
              back to queue
            </button>
          </>
        ) : (
          <>
            <button
              onClick={() => setView("open")}
              className={`px-3 py-1 rounded ${view === "open" ? "bg-admin-accent text-white" : "bg-admin-raised text-admin-muted"}`}
            >
              Open {openCount > 0 && <span className="ml-1 font-bold">({openCount})</span>}
            </button>
            <button
              onClick={() => setView("reviewed")}
              className={`px-3 py-1 rounded ${view === "reviewed" ? "bg-admin-accent text-white" : "bg-admin-raised text-admin-muted"}`}
            >
              Reviewed
            </button>
            <span className="ml-auto flex items-center gap-1">
              <button
                type="button"
                onClick={() => downloadReviewed("json")}
                disabled={exportBusy !== null}
                className="rounded border border-admin-border bg-admin-bg px-2.5 py-1 text-admin-text hover:bg-admin-raised disabled:opacity-40"
              >
                {exportBusy === "json" ? "Downloading…" : "Download JSON"}
              </button>
              <button
                type="button"
                onClick={() => downloadReviewed("csv")}
                disabled={exportBusy !== null}
                className="rounded border border-admin-border bg-admin-bg px-2.5 py-1 text-admin-text hover:bg-admin-raised disabled:opacity-40"
              >
                {exportBusy === "csv" ? "Downloading…" : "Download CSV"}
              </button>
            </span>
          </>
        )}
      </div>

      {flags.length === 0 ? (
        <div className="text-center py-10 text-sm text-admin-faint">
          {view === "open" && !sessionFilter ? "No open flags." : "Nothing here."}
        </div>
      ) : (
        <div className="space-y-2">
          {(grouped ?? flags).map((flag) => (
            <FlagRow
              key={flag.flag_id}
              flag={flag}
              now={now}
              reviewer={reviewer}
              busy={busyId === flag.flag_id}
              onReview={onReview}
              onSessionAction={onSessionAction}
              onSelectSession={setSessionFilter}
            />
          ))}
        </div>
      )}
    </div>
  )
}
