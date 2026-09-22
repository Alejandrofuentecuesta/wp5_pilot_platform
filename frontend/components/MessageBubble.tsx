"use client"

import { useEffect, useRef, useState } from "react"
import type { Message, MessageReaction } from "@/lib/types"
import { getSenderColor, PARTICIPANT_SENDER } from "@/lib/constants"
import { formatMessageTime } from "@/lib/dates"
import ReplyQuote from "./ReplyQuote"

interface MessageBubbleProps {
  message: Message
  allMessages: Message[]
  isSelf: boolean
  showSender: boolean
  displayName: string
  onReply: (msg: Message) => void
  onLike: (msg: Message) => void
  onReaction: (msg: Message, reaction: MessageReaction) => void
  onMention: (sender: string) => void
  onReport: (msg: Message) => void
  onBlock: (msg: Message) => void
}

const REACTION_OPTIONS: Array<{ value: MessageReaction; emoji: string; label: string }> = [
  { value: "laugh", emoji: "😂", label: "Risa" },
  { value: "angry", emoji: "😡", label: "Enfado" },
  { value: "sad", emoji: "😢", label: "Tristeza" },
  { value: "bored", emoji: "🥱", label: "Aburrimiento" },
  { value: "afraid", emoji: "😨", label: "Asustado/a" },
  { value: "dislike", emoji: "👎", label: "No me gusta" },
]

function renderContent(content: string, mentions?: string[]) {
  if (!mentions || mentions.length === 0) {
    return content
  }

  const escaped = mentions.map((m) =>
    m.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"),
  )
  const pattern = new RegExp(`(@(?:${escaped.join("|")}))`, "gi")
  const parts = content.split(pattern)

  return parts.map((part, i) => {
    if (pattern.test(part)) {
      pattern.lastIndex = 0
      return (
        <span key={i} className="text-mention font-medium">
          {part}
        </span>
      )
    }
    pattern.lastIndex = 0
    return part
  })
}

export default function MessageBubble({
  message,
  allMessages,
  isSelf,
  showSender,
  displayName,
  onReply,
  onLike,
  onReaction,
  onMention,
  onReport,
  onBlock,
}: MessageBubbleProps) {
  const [reactionPickerOpen, setReactionPickerOpen] = useState(false)
  const reactionPickerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!reactionPickerOpen) return

    const closeOnOutsidePress = (event: PointerEvent) => {
      if (!reactionPickerRef.current?.contains(event.target as Node)) {
        setReactionPickerOpen(false)
      }
    }
    document.addEventListener("pointerdown", closeOnOutsidePress)
    return () => document.removeEventListener("pointerdown", closeOnOutsidePress)
  }, [reactionPickerOpen])
  // The backend stores the participant's chosen display name as sender, while
  // older sessions may still use the canonical "participant" value.
  const messageIsSelf =
    isSelf ||
    message.sender === PARTICIPANT_SENDER ||
    (displayName.length > 0 && message.sender === displayName)
  const senderLabel = messageIsSelf ? displayName : message.sender

  // Replace "participant" in agent message content with the user's local
  // display name so references to the participant read naturally.
  const renderedContent =
    !messageIsSelf && displayName
      ? message.content.replace(/\bparticipant\b/g, displayName)
      : message.content
  const senderColor = getSenderColor(senderLabel)
  const likesCount = message.likes_count || 0
  const isLiked = (message.liked_by || []).includes(PARTICIPANT_SENDER)
  const selectedReaction = message.reactions?.[PARTICIPANT_SENDER]
  const selectedReactionOption = REACTION_OPTIONS.find(
    (option) => option.value === selectedReaction,
  )

  const quotedSender = message.reply_to
    ? allMessages.find((m) => m.message_id === message.reply_to)?.sender ?? ""
    : ""

  return (
    <div className={`message-card group px-3 py-0.5 ${showSender ? "mt-3" : "mt-0.5"}`}>
      <div
        className="relative bg-bg-surface rounded-lg border border-border px-3 pt-2.5 pb-2 transition-colors hover:border-secondary/20"
        style={{ borderLeftWidth: "3px", borderLeftColor: senderColor }}
      >
        {/* Top row: avatar + sender name + timestamp */}
        {showSender && (
          <div className="flex items-center gap-2 mb-1">
            <div
              className="w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-bold text-white shrink-0"
              style={{ backgroundColor: senderColor }}
            >
              {senderLabel.charAt(0).toUpperCase()}
            </div>
            <span
              className="text-[13px] font-semibold"
              style={{ color: senderColor }}
            >
              {senderLabel}
            </span>
            <span className="text-[11px] text-tertiary ml-auto">
              {formatMessageTime(message.timestamp)}
            </span>
          </div>
        )}

        {/* Continuation: float timestamp */}
        {!showSender && (
          <span className="float-right text-[11px] text-tertiary ml-2 mt-0.5">
            {formatMessageTime(message.timestamp)}
          </span>
        )}

        {/* Reply quote */}
        {message.quoted_text && (
          <ReplyQuote
            sender={quotedSender}
            text={
              message.quoted_text.length > 150
                ? message.quoted_text.slice(0, 150) + "\u2026"
                : message.quoted_text
            }
          />
        )}

        {/* Message content */}
        <p className="text-[14px] text-primary leading-[1.45] whitespace-pre-wrap break-words">
          {renderContent(renderedContent, message.mentions)}
        </p>

        {/* Action buttons row */}
        <div className="relative flex flex-wrap items-center gap-1 mt-1.5 -mb-0.5">
          <button
            onClick={() => onReply(message)}
            className="inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] text-secondary hover:bg-accent-soft hover:text-accent transition-colors"
            aria-label="Responder a este mensaje"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <polyline points="9 17 4 12 9 7" />
              <path d="M20 18v-2a4 4 0 00-4-4H4" />
            </svg>
            Responder
          </button>

          <button
            onClick={() => onLike(message)}
            className={`inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] transition-colors ${
              isLiked
                ? "bg-red-50 text-danger"
                : "text-secondary hover:bg-red-50 hover:text-danger"
            }`}
            aria-label={isLiked ? "Quitar Me gusta" : "Marcar Me gusta"}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill={isLiked ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M20.84 4.61a5.5 5.5 0 00-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 00-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 000-7.78z" />
            </svg>
            Me gusta{likesCount > 0 ? ` ${likesCount}` : ""}
          </button>

          <div ref={reactionPickerRef} className="relative">
            <button
              onClick={() => setReactionPickerOpen((open) => !open)}
              className={`inline-flex items-center gap-1 rounded px-2 py-1 text-[11px] transition-colors ${selectedReaction ? "bg-accent-soft text-accent" : "text-secondary hover:bg-accent-soft hover:text-accent"}`}
              aria-label="Reaccionar al mensaje"
              aria-expanded={reactionPickerOpen}
            >
              <span aria-hidden="true">{selectedReactionOption?.emoji || "☺"}</span>
              Reaccionar
            </button>
            {reactionPickerOpen && (
              <div className="absolute bottom-full left-0 z-20 mb-1 flex gap-1 rounded-lg border border-border bg-white p-1.5 shadow-lg" role="menu" aria-label="Elegir reacción">
                {REACTION_OPTIONS.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    title={option.label}
                    aria-label={option.label}
                    aria-pressed={selectedReaction === option.value}
                    onClick={() => {
                      onReaction(message, option.value)
                      setReactionPickerOpen(false)
                    }}
                    className={`flex h-8 w-8 items-center justify-center rounded text-lg transition-colors hover:bg-bg-feed ${selectedReaction === option.value ? "bg-accent-soft ring-1 ring-accent" : ""}`}
                  >
                    {option.emoji}
                  </button>
                ))}
              </div>
            )}
          </div>

          {!messageIsSelf && (
            <button
              onClick={() => onMention(message.sender)}
              className="inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] text-secondary hover:bg-accent-soft hover:text-accent transition-colors"
              aria-label={`Mencionar a ${message.sender}`}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <circle cx="12" cy="12" r="4" />
                <path d="M16 8v5a3 3 0 006 0v-1a10 10 0 10-3.92 7.94" />
              </svg>
              Mencionar
            </button>
          )}

          {!messageIsSelf && (
            <button
              onClick={() => onReport(message)}
              className={`inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] transition-colors ${
                message.reported
                  ? "bg-red-50 text-danger"
                  : "text-secondary hover:text-danger hover:bg-red-50"
              }`}
              aria-label="Reportar este mensaje"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill={message.reported ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z" />
                <line x1="4" y1="22" x2="4" y2="15" />
              </svg>
              Reportar
            </button>
          )}

          {!messageIsSelf && (
            <button
              onClick={() => onBlock(message)}
              className="inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] text-secondary hover:text-danger hover:bg-red-50 transition-colors"
              aria-label={`Bloquear a ${message.sender}`}
            >
              <svg
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <circle cx="12" cy="12" r="9" />
                <line x1="5.6" y1="18.4" x2="18.4" y2="5.6" />
              </svg>
              Bloquear
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
