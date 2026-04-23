"use client"

import { useEffect, useState } from "react"
import type { Message } from "@/lib/types"
import type { ParticipantStance } from "@/lib/types"
import { formatMessageTime } from "@/lib/dates"

interface NewsArticleModalProps {
  message: Message
  open: boolean
  onClose: () => void
  participantStance: ParticipantStance | null
  onConfirmParticipantStance: (stance: ParticipantStance) => Promise<void>
}

export default function NewsArticleModal({
  message,
  open,
  onClose,
  participantStance,
  onConfirmParticipantStance,
}: NewsArticleModalProps) {
  const [selectedStance, setSelectedStance] = useState<ParticipantStance | "">(participantStance || "")
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    if (open) {
      setSelectedStance(participantStance || "")
      setError("")
      setSaving(false)
    }
  }, [open, participantStance])

  if (!open) return null

  const title = message.headline || "News article"
  const source = message.source || "Source not specified"
  const body = message.body || message.content
  const combinedText = `${title}\n${body}`.toLowerCase()
  const topicQualifiedAgainstLabel = /(climate|clima|emissions|emisiones|co2|carbon|fossil|global warming|calentamiento)/.test(combinedText)
    ? "In favor of climate action, but against this measure"
    : /(immigration|inmigr|migrant|migraci|asylum|refugee|frontera|border)/.test(combinedText)
      ? "Pro immigration, but against this measure"
      : "In favor of the topic, but against this measure"
  const stanceLabels: Record<NonNullable<ParticipantStance>, string> = {
    favor: "In favor of the measure",
    against: "Against the measure",
    qualified_favor: "In favor, but with important reservations",
    qualified_against: topicQualifiedAgainstLabel,
    skeptical: "Skeptical / unsure",
  }
  const currentStance = selectedStance || participantStance
  const stanceLabel = currentStance ? stanceLabels[currentStance] : "Not selected"

  const handleConfirm = async () => {
    if (!selectedStance) {
      setError("Please choose your position before continuing.")
      return
    }
    setSaving(true)
    setError("")
    try {
      await onConfirmParticipantStance(selectedStance)
      onClose()
    } catch {
      setError("Could not save your answer. Please try again.")
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 bg-black/55 backdrop-blur-sm flex items-start sm:items-center justify-center px-3 py-3 sm:px-4 sm:py-6 overflow-y-auto"
      role="dialog"
      aria-modal="true"
      aria-labelledby="news-article-title"
    >
      <div className="w-full max-w-3xl max-h-[92vh] rounded-2xl border border-border bg-bg-surface shadow-2xl overflow-hidden flex flex-col">
        <div className="h-1 bg-accent" />
        <div className="p-4 sm:p-6 space-y-4 min-h-0 flex-1 flex flex-col">
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-1">
              <p className="text-[11px] uppercase tracking-[0.18em] text-secondary font-semibold">
                News article
              </p>
              <h2 id="news-article-title" className="text-2xl font-semibold text-primary leading-tight">
                {title}
              </h2>
              <p className="text-sm text-secondary">
                {source} {message.timestamp ? `· ${formatMessageTime(message.timestamp)}` : ""}
              </p>
              <p className="inline-flex items-center rounded-full border border-border bg-bg-feed px-2.5 py-1 text-[11px] font-medium text-secondary">
                Self-report: {stanceLabel}
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="shrink-0 rounded-full border border-border px-3 py-1.5 text-xs font-medium text-secondary hover:text-primary hover:border-accent transition-colors"
            >
              Continue
            </button>
          </div>

          <div className="rounded-xl bg-bg-feed border border-border/70 p-4 sm:p-5 overflow-y-auto flex-1 min-h-0">
            <p className="text-[15px] leading-7 text-primary whitespace-pre-wrap pr-1">
              {body}
            </p>
          </div>

          <div className="rounded-xl border border-border bg-bg-surface p-4 space-y-3 shrink-0">
            <div className="space-y-1">
              <p className="text-sm font-medium text-primary">
                What is your position on this article?
              </p>
              <p className="text-xs text-secondary">
                This self-report is used as a hint for agent selection in agent-based mode. The Director still uses the study criteria and your actual messages to infer stance.
              </p>
            </div>
            <select
              value={selectedStance}
              onChange={(e) => setSelectedStance(e.target.value as ParticipantStance | "")}
              className="w-full px-3 py-2.5 border border-border rounded-lg text-sm text-primary focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/30 transition-colors bg-bg-surface"
            >
              <option value="" disabled>
                Select one option
              </option>
              <option value="favor">In favor of the measure</option>
              <option value="against">Against the measure</option>
              <option value="qualified_against">{topicQualifiedAgainstLabel}</option>
            </select>
            <p className="text-xs text-secondary">
              Selected: <span className="font-medium text-primary">{stanceLabel}</span>
            </p>
            {error && <p className="text-sm text-danger">{error}</p>}
            <button
              type="button"
              onClick={handleConfirm}
              disabled={saving}
              className="px-4 py-2 rounded-lg bg-accent text-white text-sm font-medium hover:bg-accent-hover transition-colors disabled:opacity-50"
            >
              {saving ? "Saving..." : "Continue"}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
