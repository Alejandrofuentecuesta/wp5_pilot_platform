"use client"

import { useEffect, useRef, Fragment } from "react"
import type { Message } from "@/lib/types"
import { getDateLabel } from "@/lib/dates"
import { PARTICIPANT_SENDER } from "@/lib/constants"
import MessageBubble from "./MessageBubble"
import NewsArticleCard from "./NewsArticleCard"
import DateSeparator from "./DateSeparator"

interface MessageFeedProps {
  messages: Message[]
  displayName: string
  typingCount: number
  onReply: (msg: Message) => void
  onLike: (msg: Message) => void
  onMention: (sender: string) => void
  onReport: (msg: Message) => void
  onArticleClick?: (msg: Message) => void
}

function TypingDots() {
  return (
    <span className="inline-flex ml-0.5 gap-[2px]">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="inline-block w-[3px] h-[3px] rounded-full bg-secondary animate-bounce"
          style={{ animationDelay: `${i * 0.15}s`, animationDuration: "0.6s" }}
        />
      ))}
    </span>
  )
}

interface DateGroup {
  label: string
  dateKey: string
  messages: Message[]
}

function groupByDate(messages: Message[]): DateGroup[] {
  const groups: DateGroup[] = []
  let current: DateGroup | null = null

  for (const msg of messages) {
    const label = getDateLabel(msg.timestamp)
    if (!current || current.label !== label) {
      current = { label, dateKey: msg.timestamp.slice(0, 10), messages: [] }
      groups.push(current)
    }
    current.messages.push(msg)
  }

  return groups
}

export default function MessageFeed({
  messages,
  displayName,
  typingCount,
  onReply,
  onLike,
  onMention,
  onReport,
  onArticleClick,
}: MessageFeedProps) {
  const feedRef = useRef<HTMLDivElement>(null)

  // Scroll only the feed. scrollIntoView() can also move the document viewport,
  // leaving the fixed-height chat partially off-screen on short windows.
  useEffect(() => {
    const feed = feedRef.current
    if (!feed) return
    feed.scrollTo({ top: feed.scrollHeight, behavior: "smooth" })
  }, [messages.length])

  const dateGroups = groupByDate(messages)

  return (
    <div
      ref={feedRef}
      className="min-h-0 flex-1 overflow-y-auto overscroll-contain chat-scrollbar bg-bg-feed py-2"
    >
      {dateGroups.map((group) => (
        <Fragment key={group.dateKey}>
          <DateSeparator label={group.label} />
          {group.messages.map((msg, idx) => {
            const isSelf = msg.sender === PARTICIPANT_SENDER

            if (msg.msg_type === "news_article") {
              return (
                <NewsArticleCard
                  key={msg.message_id}
                  message={msg}
                  onClick={onArticleClick ? () => onArticleClick(msg) : undefined}
                />
              )
            }

            // Show sender name on first message in a sender group
            const prevMsg = idx > 0 ? group.messages[idx - 1] : null
            const showSender =
              !prevMsg ||
              prevMsg.sender !== msg.sender ||
              prevMsg.msg_type === "news_article"

            return (
              <MessageBubble
                key={msg.message_id}
                message={msg}
                allMessages={messages}
                isSelf={isSelf}
                showSender={showSender}
                displayName={displayName}
                onReply={onReply}
                onLike={onLike}
                onMention={onMention}
                onReport={onReport}
              />
            )
          })}
        </Fragment>
      ))}
      {typingCount > 0 && (
        <div className="px-4 py-2 text-xs text-secondary italic">
          {typingCount === 1
            ? "Someone is writing a message"
            : `${typingCount} people are writing a message`}
          <TypingDots />
        </div>
      )}
    </div>
  )
}
