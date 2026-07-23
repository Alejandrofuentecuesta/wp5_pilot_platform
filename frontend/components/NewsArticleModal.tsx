"use client"

import { useState } from "react"
import { formatMessageTime } from "@/lib/dates"
import type { ParticipantStance } from "@/lib/types"
import type { Message } from "@/lib/types"

interface NewsArticleModalProps {
  message: Message
  open: boolean
  onClose: () => void
  participantStance: ParticipantStance | null
  isInitialRead?: boolean
  onSubmitInitialMessage?: (initialMessage: string) => void
}

export default function NewsArticleModal({
  message,
  open,
  onClose,
  participantStance,
  isInitialRead = false,
  onSubmitInitialMessage,
}: NewsArticleModalProps) {
  const [initialInput, setInitialInput] = useState("")

  if (!open) return null

  const title = message.headline || "News article"
  const source = message.source || "Source not specified"
  const body = message.body || message.content

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!initialInput.trim()) return
    if (onSubmitInitialMessage) {
      onSubmitInitialMessage(initialInput.trim())
    } else {
      onClose()
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
            </div>
            {!isInitialRead && (
              <button
                type="button"
                onClick={onClose}
                className="shrink-0 rounded-full border border-border px-3 py-1.5 text-xs font-medium text-secondary hover:text-primary hover:border-accent transition-colors"
              >
                Cerrar
              </button>
            )}
          </div>

          <div className="rounded-xl bg-bg-feed border border-border/70 p-4 sm:p-5 overflow-y-auto flex-1 min-h-0">
            <p className="text-[15px] leading-7 text-primary whitespace-pre-wrap pr-1">
              {body}
            </p>
          </div>

          {isInitialRead && (
            <form onSubmit={handleSubmit} className="mt-2 space-y-3 pt-3 border-t border-border/60 shrink-0">
              <div>
                <label htmlFor="initial-reaction-input" className="block text-xs font-semibold text-primary mb-1 uppercase tracking-wider">
                  Escribe tu mensaje inicial para unirte al debate
                </label>
                <textarea
                  id="initial-reaction-input"
                  rows={2}
                  value={initialInput}
                  onChange={(e) => setInitialInput(e.target.value)}
                  placeholder="¿Qué opinas sobre esta noticia? Escribe tu mensaje inicial aquí..."
                  className="w-full rounded-xl border border-border bg-bg-surface p-3 text-sm text-primary transition-colors placeholder:text-tertiary focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent/30 resize-none"
                  autoFocus
                />
              </div>
              <div className="flex justify-end">
                <button
                  type="submit"
                  disabled={!initialInput.trim()}
                  className="rounded-xl bg-accent px-5 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
                >
                  Publicar y entrar al chat
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}

