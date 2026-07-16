"use client"

import type { Message } from "@/lib/types"
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
  onMention: (sender: string) => void
  onReport: (msg: Message) => void
}

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
  onMention,
  onReport,
}: MessageBubbleProps) {
  // For display: show the user's local display name instead of "participant"
  const senderLabel = isSelf ? displayName : message.sender

  // Replace "participant" in agent message content with the user's local
  // display name so references to the participant read naturally.
  const renderedContent =
    !isSelf && displayName
      ? message.content.replace(/\bparticipant\b/g, displayName)
      : message.content
  const senderColor = getSenderColor(senderLabel)
  const likesCount = message.likes_count || 0
  const isLiked = (message.liked_by || []).includes(PARTICIPANT_SENDER)

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
        <div className="flex items-center gap-1 mt-1.5 -mb-0.5">
          <button
            onClick={() => onReply(message)}
            className="inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] text-secondary hover:bg-accent-soft hover:text-accent transition-colors"
            aria-label="Reply to this message"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <polyline points="9 17 4 12 9 7" />
              <path d="M20 18v-2a4 4 0 00-4-4H4" />
            </svg>
            Reply
          </button>

          <button
            onClick={() => onLike(message)}
            className={`inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] transition-colors ${
              isLiked
                ? "bg-red-50 text-danger"
                : "text-secondary hover:bg-red-50 hover:text-danger"
            }`}
            aria-label={isLiked ? "Unlike this message" : "Like this message"}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill={isLiked ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M20.84 4.61a5.5 5.5 0 00-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 00-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 000-7.78z" />
            </svg>
            {likesCount > 0 ? likesCount : "Like"}
          </button>

          {!isSelf && (
            <button
              onClick={() => onMention(message.sender)}
              className="inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] text-secondary hover:bg-accent-soft hover:text-accent transition-colors"
              aria-label={`Mention ${message.sender}`}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <circle cx="12" cy="12" r="4" />
                <path d="M16 8v5a3 3 0 006 0v-1a10 10 0 10-3.92 7.94" />
              </svg>
              Mention
            </button>
          )}

          {!isSelf && (
            <button
              onClick={() => onReport(message)}
              className={`inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] transition-colors ${
                message.reported
                  ? "bg-red-50 text-danger"
                  : "text-secondary hover:text-danger hover:bg-red-50"
              }`}
              aria-label="Report this message"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill={message.reported ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z" />
                <line x1="4" y1="22" x2="4" y2="15" />
              </svg>
              Report
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
