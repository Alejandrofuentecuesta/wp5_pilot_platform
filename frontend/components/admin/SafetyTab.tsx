"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  getSafetyPolicy,
  getSafetySummary,
  listSafetyFlags,
  reviewSafetyFlag,
  safetySessionAction,
  saveSafetyPolicy,
} from "../../lib/admin-api"
import type { SafetyFlag, SafetyPolicy, SafetyPolicyCategory, SafetySummary } from "../../lib/admin-types"

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
  const paused = !!flag.safety_paused_at
  const canAct = flag.live && !!reviewer
  const canPublishWithheld =
    !isParticipant &&
    !flag.displayed_at &&
    flag.verdict === "unsafe" &&
    flag.categories.length > 0

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
            {elapsed === null ? "withheld" : `seen ${fmtElapsed(elapsed)} ago`}
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

      {flag.context_user_turn && !isParticipant && (
        <div className="mt-1">
          <button className="text-[11px] text-admin-faint hover:text-admin-text underline" onClick={() => setShowContext((v) => !v)}>
            {showContext ? "hide" : "show"} the participant turn it was judged against
          </button>
          {showContext && (
            <p className="mt-1 text-xs text-admin-muted whitespace-pre-wrap border-l-2 border-admin-border pl-2">
              {flag.context_user_turn}
            </p>
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

const CONTEXT_MODE_HELP: Record<SafetyPolicy["context_mode"], string> = {
  none: "Agent messages are judged on their own.",
  conditional: "The participant's last message is included only when that message was itself flagged (catches agents endorsing a participant's hate or violence).",
  always: "The participant's last message is always included (highest sensitivity; the model also reacts to what the participant said).",
}

/* Classifier model: which LLM screens messages. "Llama Guard" leaves
   transport/model unset so the experiment falls back to the self-hosted
   SAFETY_TRANSPORT / SAFETY_BASE_URL / SAFETY_MODEL env vars, unchanged from
   before this selector existed. "Claude" routes through the
   anthropic_messages transport with its own prompt (utils.safety.prompt's
   render_chat_prompt) that returns the same safe/unsafe + categories verdict
   plus a one-sentence rationale. */
type ClassifierKey = "llama_guard" | "claude"

const CLASSIFIER_OPTIONS: { key: ClassifierKey; label: string; defaultModel: string }[] = [
  { key: "llama_guard", label: "Llama Guard 3 (self-hosted)", defaultModel: "" },
  { key: "claude", label: "Claude (Anthropic API)", defaultModel: "claude-haiku-4-5-20251001" },
]

function classifierKeyFor(transport: string | null): ClassifierKey {
  return transport === "anthropic_messages" ? "claude" : "llama_guard"
}

function PolicyPanel({ adminKey, experimentId }: { adminKey: string; experimentId: string }) {
  const [policy, setPolicy] = useState<SafetyPolicy | null>(null)
  const [draft, setDraft] = useState<SafetyPolicy | null>(null)
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null)

  const load = useCallback(async () => {
    try {
      const p = await getSafetyPolicy(adminKey, experimentId)
      setPolicy(p)
      setDraft((prev) => (prev && prev.experiment_id === p.experiment_id && !saving ? prev : p))
    } catch (e) {
      setMsg({ kind: "err", text: e instanceof Error ? e.message : "Failed to load policy" })
    }
  }, [adminKey, experimentId, saving])

  useEffect(() => {
    load()
  }, [load])

  if (!policy || !draft) return null

  const dirty =
    draft.enabled !== policy.enabled ||
    JSON.stringify(draft.categories) !== JSON.stringify(policy.categories) ||
    draft.context_mode !== policy.context_mode ||
    draft.transport !== policy.transport ||
    draft.model !== policy.model
  const enabledCount = draft.categories.filter((c) => c.enabled).length

  const setCat = (code: string, patch: Partial<SafetyPolicyCategory>) =>
    setDraft({ ...draft, categories: draft.categories.map((c) => (c.code === code ? { ...c, ...patch } : c)) })

  const save = async () => {
    setSaving(true)
    setMsg(null)
    try {
      const p = await saveSafetyPolicy(adminKey, experimentId, {
        enabled: draft.enabled,
        context_mode: draft.context_mode,
        categories: draft.categories.map((c) => ({
          code: c.code,
          title: c.title,
          enabled: c.enabled,
          definition: c.definition.trim() || undefined,
        })),
        transport: draft.transport,
        model: draft.model,
      })
      setPolicy(p)
      setDraft(p)
      setMsg({ kind: "ok", text: "Saved. Applies to sessions started from now on; live sessions keep the policy they started with." })
    } catch (e) {
      setMsg({ kind: "err", text: e instanceof Error ? e.message : "Save failed" })
    } finally {
      setSaving(false)
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
            {experimentId} · {policy.enabled ? `${policy.categories.filter((c) => c.enabled).length}/14 categories · context: ${policy.context_mode}` : "screening disabled"}
          </span>
          {policy.locked && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-admin-pastel-amber text-admin-pastel-amber-text">locked</span>
          )}
        </div>
        <span className="text-xs text-admin-faint">{open ? "hide" : "edit"}</span>
      </button>

      {open && (
        <div className="px-4 pb-4 space-y-4 border-t border-admin-border pt-3">
          {policy.locked && (
            <p className="text-xs text-admin-pastel-amber-text">
              This policy is locked for fieldwork. Changes require unlocking through the API.
            </p>
          )}

          <div className={`rounded-lg border px-3 py-3 ${draft.enabled ? "border-admin-pastel-green bg-admin-pastel-green/20" : "border-admin-danger bg-admin-danger-soft/40"}`}>
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-semibold text-admin-text">
                  LlamaGuard screening is {draft.enabled ? "enabled" : "disabled"}
                </div>
                <p className="mt-1 text-xs text-admin-muted">
                  {draft.enabled
                    ? "Agent messages are screened before reaching participants. If the model is unavailable, agent turns may be withheld."
                    : "Agent messages are not screened by LlamaGuard. Use this when the safety model is unavailable or for local tests."}
                </p>
              </div>
              <button
                type="button"
                disabled={policy.locked || saving}
                onClick={() => setDraft({ ...draft, enabled: !draft.enabled })}
                className={`shrink-0 rounded border px-3 py-1 text-xs font-medium shadow-sm disabled:opacity-40 ${
                  draft.enabled
                    ? "border-red-700 bg-red-600 text-white hover:bg-red-700"
                    : "border-admin-accent bg-admin-accent text-white hover:bg-admin-accent-hover"
                }`}
              >
                {draft.enabled ? "Disable LlamaGuard" : "Enable LlamaGuard"}
              </button>
            </div>
            <p className="mt-2 text-[11px] text-admin-faint">
              This applies to sessions started after saving; live sessions keep the policy they started with.
            </p>
          </div>

          <div>
            <label className="block text-xs font-medium text-admin-text mb-1">Classifier model</label>
            <div className="flex flex-wrap gap-2">
              {CLASSIFIER_OPTIONS.map((opt) => {
                const active = classifierKeyFor(draft.transport) === opt.key
                return (
                  <button
                    key={opt.key}
                    type="button"
                    disabled={policy.locked}
                    onClick={() =>
                      setDraft({
                        ...draft,
                        transport: opt.key === "llama_guard" ? null : "anthropic_messages",
                        model: opt.key === "llama_guard" ? null : draft.model || opt.defaultModel,
                      })
                    }
                    className={`rounded border px-3 py-1.5 text-xs font-medium shadow-sm disabled:opacity-40 ${
                      active
                        ? "border-admin-accent bg-admin-accent text-white"
                        : "border-admin-border bg-admin-bg text-admin-text hover:bg-admin-raised"
                    }`}
                  >
                    {opt.label}
                  </button>
                )
              })}
            </div>
            {classifierKeyFor(draft.transport) === "claude" && (
              <div className="mt-2">
                <label className="block text-[11px] text-admin-faint mb-1">Model id</label>
                <input
                  type="text"
                  disabled={policy.locked}
                  value={draft.model || ""}
                  onChange={(e) => setDraft({ ...draft, model: e.target.value })}
                  placeholder="claude-haiku-4-5-20251001"
                  className="w-full max-w-xs border border-admin-border rounded px-2 py-1 text-xs bg-admin-bg text-admin-text"
                />
              </div>
            )}
            <p className="text-[11px] text-admin-faint mt-1">
              {classifierKeyFor(draft.transport) === "claude"
                ? "Uses the Anthropic API (ANTHROPIC_API_KEY) with a prompt built to return the same safe/unsafe + categories verdict as Llama Guard, plus a one-sentence rationale shown on each flag."
                : "Uses the self-hosted Llama Guard 3 endpoint (SAFETY_BASE_URL / SAFETY_MODEL, or this experiment's own override once set)."}
            </p>
          </div>

          <div>
            <label className="block text-xs font-medium text-admin-text mb-1">Participant context</label>
            <select
              value={draft.context_mode}
              disabled={policy.locked}
              onChange={(e) => setDraft({ ...draft, context_mode: e.target.value as SafetyPolicy["context_mode"] })}
              className="border border-admin-border rounded px-2 py-1 text-xs bg-admin-bg text-admin-text"
            >
              <option value="none">none</option>
              <option value="conditional">conditional</option>
              <option value="always">always</option>
            </select>
            <p className="text-[11px] text-admin-faint mt-1">{CONTEXT_MODE_HELP[draft.context_mode]}</p>
          </div>

          <div>
            <div className="text-xs font-medium text-admin-text mb-1">
              Categories <span className="text-admin-faint font-normal">({enabledCount}/14 enabled; a disabled category is left out of the prompt entirely)</span>
            </div>
            <div className="space-y-1">
              {draft.categories.map((c) => (
                <div key={c.code} className={`grid grid-cols-[auto_9rem_1fr] gap-2 items-start py-1 ${c.enabled ? "" : "opacity-60"}`}>
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={c.enabled}
                    disabled={policy.locked}
                    onChange={(e) => setCat(c.code, { enabled: e.target.checked })}
                  />
                  <span className="text-xs text-admin-text pt-0.5">
                    <span className="font-mono">{c.code}</span> {c.name}
                  </span>
                  <textarea
                    value={c.definition}
                    disabled={policy.locked || !c.enabled}
                    onChange={(e) => setCat(c.code, { definition: e.target.value })}
                    rows={c.definition ? 3 : 1}
                    placeholder="optional description (blank = the model's default understanding of this category)"
                    className="w-full border border-admin-border rounded px-2 py-1 text-xs bg-admin-bg text-admin-text resize-y"
                  />
                </div>
              ))}
            </div>
          </div>

          {msg && (
            <p className={`text-xs ${msg.kind === "ok" ? "text-admin-pastel-green-text" : "text-admin-danger-text"}`}>{msg.text}</p>
          )}

          <div className="flex items-center gap-2">
            <button
              disabled={policy.locked || !dirty || saving || (draft.enabled && enabledCount === 0)}
              onClick={save}
              className="px-3 py-1 rounded text-xs font-medium bg-admin-accent text-white disabled:opacity-40"
            >
              {saving ? "Saving…" : "Save policy"}
            </button>
            <button
              disabled={!dirty || saving}
              onClick={() => setDraft(policy)}
              className="px-3 py-1 rounded text-xs bg-admin-raised text-admin-muted disabled:opacity-40"
            >
              Discard changes
            </button>
          </div>
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
            Every flagged message needs a named review. Agent rows are grey; participant rows are purple.
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
