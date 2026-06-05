"use client"

import { formatMessageTime } from "@/lib/dates"
import type { ParticipantStance } from "@/lib/types"
import type { Message } from "@/lib/types"

interface NewsArticleModalProps {
  message: Message
  open: boolean
  onClose: () => void
  participantStance: ParticipantStance | null
}

const STANCE_LABELS: Record<ParticipantStance, string> = {
  pro_topic: "Column I / pro-topic",
  anti_topic: "Column II / anti-topic",
}

export default function NewsArticleModal({
  message,
  open,
  onClose,
  participantStance,
}: NewsArticleModalProps) {
  if (!open) return null

  const title = message.headline || "News article"
  const source = message.source || "Source not specified"
  const body = message.body || message.content
  const stanceLabel = participantStance ? STANCE_LABELS[participantStance] : "Not recorded"

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
                Recorded position: {stanceLabel}
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
        </div>
      </div>
    </div>
  )
}
