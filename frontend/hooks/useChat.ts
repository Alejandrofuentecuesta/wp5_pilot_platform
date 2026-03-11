import { useState, useCallback, useMemo } from "react"
import { useWebSocket } from "./useWebSocket"
import { useLocalStorage } from "./useLocalStorage"
import { PARTICIPANT_SENDER, LS_SESSION_ID, LS_USERNAME, LS_BLOCKED } from "@/lib/constants"
import {
  startSession as apiStartSession,
  likeMessage as apiLikeMessage,
  reportMessage as apiReportMessage,
} from "@/lib/api"
import { detectMentions } from "@/lib/mentions"
import type {
  Message,
  BlockedSenders,
  UserMessagePayload,
  LikeEvent,
  ReportEvent,
  BlockEvent,
} from "@/lib/types"

export function useChat() {
  // Session state
  const [sessionId, setSessionId] = useLocalStorage<string | null>(
    LS_SESSION_ID,
    null,
  )
  const [username, setUsername] = useLocalStorage<string>(LS_USERNAME, "")
  const [blockedSenders, setBlockedSenders] = useLocalStorage<BlockedSenders>(
    LS_BLOCKED,
    {},
  )

  // Session end state
  const [sessionEnded, setSessionEnded] = useState(false)
  const [redirectUrl, setRedirectUrl] = useState<string | null>(null)

  // Chat state
  const [messages, setMessages] = useState<Message[]>([])
  const [replyTo, setReplyTo] = useState<Message | null>(null)
  const [inputValue, setInputValue] = useState("")

  // Typing indicator state (count of agents currently typing)
  const [typingCount, setTypingCount] = useState(0)

  // Report modal state
  const [reportModalOpen, setReportModalOpen] = useState(false)
  const [reportTarget, setReportTarget] = useState<Message | null>(null)
  const [reporting, setReporting] = useState(false)

  // Derived: participants list from observed senders
  const participants = useMemo(() => {
    const set = new Set(
      messages.map((m) => m.sender).filter((s) => !s.startsWith("[")),
    )
    return [...set]
  }, [messages])

  // Derived: detected mentions from current input
  const detectedMentions = useMemo(
    () => detectMentions(inputValue, participants),
    [inputValue, participants],
  )

  // WebSocket message handler
  const handleWSMessage = useCallback((data: unknown) => {
    const obj = data as Record<string, unknown>
    if (obj && obj.event_type === "message_like") {
      const evt = obj as unknown as LikeEvent
      setMessages((prev) =>
        prev.map((m) =>
          m.message_id === evt.message_id
            ? { ...m, likes_count: evt.likes_count, liked_by: evt.liked_by }
            : m,
        ),
      )
    } else if (obj && obj.event_type === "message_report") {
      const evt = obj as unknown as ReportEvent
      setMessages((prev) =>
        prev.map((m) =>
          m.message_id === evt.message_id
            ? { ...m, reported: evt.reported }
            : m,
        ),
      )
    } else if (obj && obj.event_type === "typing_start") {
      setTypingCount((prev) => prev + 1)
    } else if (obj && obj.event_type === "typing_stop") {
      setTypingCount((prev) => Math.max(0, prev - 1))
    } else if (obj && obj.event_type === "session_end") {
      const url = (obj as Record<string, unknown>).redirect_url as string | undefined
      setSessionEnded(true)
      setRedirectUrl(url || null)
      // Clear session so user can't refresh back into the chatroom
      setSessionId(null)
    } else if (obj && obj.event_type === "user_block") {
      const evt = obj as unknown as BlockEvent
      if (evt.blocked && typeof evt.blocked === "object") {
        setBlockedSenders(evt.blocked)
      }
    } else {
      const message = obj as unknown as Message
      setMessages((prev) => [...prev, message])
    }
  }, [setBlockedSenders, setSessionId])

  const handleSessionInvalid = useCallback(() => {
    setSessionId(null)
    alert(
      "Session invalid or expired. Please enter your token to start a new session.",
    )
  }, [setSessionId])

  const { isConnected, send } = useWebSocket({
    sessionId,
    onMessage: handleWSMessage,
    onSessionInvalid: handleSessionInvalid,
  })

  // Start session — username never leaves the frontend (privacy by design).
  // The backend always uses "participant" as the sender identity.
  const startSession = async (token: string, name: string) => {
    const data = await apiStartSession(token)
    setSessionId(data.session_id)
    if (name) setUsername(name)
  }

  // Send message
  const sendMessage = () => {
    if (!inputValue.trim()) return
    const content = inputValue.trim()
    const payload: UserMessagePayload = { type: "user_message", content }
    if (replyTo) {
      payload.reply_to = replyTo.message_id
      payload.quoted_text = replyTo.content
    }
    if (detectedMentions.length > 0) payload.mentions = detectedMentions

    send(payload)

    setInputValue("")
    setReplyTo(null)
  }

  // Like message (with optimistic update + rollback)
  const toggleLike = async (msg: Message) => {
    if (!sessionId) return
    const uid = PARTICIPANT_SENDER

    // Optimistic update
    setMessages((prev) =>
      prev.map((mm) => {
        if (mm.message_id !== msg.message_id) return mm
        const likedBy = new Set(mm.liked_by || [])
        if (likedBy.has(uid)) {
          likedBy.delete(uid)
        } else {
          likedBy.add(uid)
        }
        return {
          ...mm,
          liked_by: Array.from(likedBy),
          likes_count: likedBy.size,
        }
      }),
    )

    try {
      const data = await apiLikeMessage(sessionId, msg.message_id, uid)
      const serverMsg = data.message
      // Reconcile with server
      setMessages((prev) =>
        prev.map((mm) =>
          mm.message_id === serverMsg.message_id
            ? {
                ...mm,
                likes_count: serverMsg.likes_count,
                liked_by: serverMsg.liked_by,
              }
            : mm,
        ),
      )
    } catch {
      // Revert optimistic update
      setMessages((prev) =>
        prev.map((mm) => {
          if (mm.message_id !== msg.message_id) return mm
          const likedBy = new Set(mm.liked_by || [])
          if (likedBy.has(uid)) {
            likedBy.delete(uid)
          } else {
            likedBy.add(uid)
          }
          return {
            ...mm,
            liked_by: Array.from(likedBy),
            likes_count: likedBy.size,
          }
        }),
      )
    }
  }

  // Report message (with optimistic update + rollback)
  const performReport = async (block: boolean) => {
    if (!reportTarget || !sessionId) return
    setReporting(true)
    const uid = PARTICIPANT_SENDER
    const messageId = reportTarget.message_id
    const sender = reportTarget.sender

    // Prevent reporting yourself
    if (sender === uid) {
      setReporting(false)
      setReportModalOpen(false)
      setReportTarget(null)
      return
    }

    const prevReported = reportTarget.reported || false

    // Optimistic update
    setMessages((prev) =>
      prev.map((mm) =>
        mm.message_id === messageId ? { ...mm, reported: true } : mm,
      ),
    )
    if (block) {
      const nowIso = new Date().toISOString()
      setBlockedSenders((prev) => {
        if (prev[sender]) return prev
        return { ...prev, [sender]: nowIso }
      })
    }

    try {
      const data = await apiReportMessage(sessionId, messageId, uid, block)
      const serverMsg = data.message
      setMessages((prev) =>
        prev.map((mm) =>
          mm.message_id === serverMsg.message_id
            ? { ...mm, reported: serverMsg.reported }
            : mm,
        ),
      )
      if (data.blocked && typeof data.blocked === "object") {
        setBlockedSenders(data.blocked)
      }
    } catch {
      // Revert
      setMessages((prev) =>
        prev.map((mm) =>
          mm.message_id === messageId
            ? { ...mm, reported: prevReported }
            : mm,
        ),
      )
      if (block) {
        setBlockedSenders((prev) => {
          const next = { ...prev }
          delete next[sender]
          return next
        })
      }
    } finally {
      setReporting(false)
      setReportModalOpen(false)
      setReportTarget(null)
    }
  }

  // Filtered messages (respecting blocked senders)
  const visibleMessages = useMemo(() => {
    return messages.filter((msg) => {
      const blockedIso = blockedSenders[msg.sender]
      if (!blockedIso) return true
      try {
        return new Date(msg.timestamp) < new Date(blockedIso)
      } catch {
        return true
      }
    })
  }, [messages, blockedSenders])

  return {
    // Session
    sessionId,
    username,
    setUsername,
    startSession,
    // Connection
    isConnected,
    // Messages
    visibleMessages,
    participants,
    // Input
    inputValue,
    setInputValue,
    detectedMentions,
    // Reply
    replyTo,
    setReplyTo,
    // Send
    sendMessage,
    // Like
    toggleLike,
    // Report
    reportModalOpen,
    setReportModalOpen,
    reportTarget,
    setReportTarget,
    reporting,
    performReport,
    // Blocked
    blockedSenders,
    // Typing indicator
    typingCount,
    // Session end
    sessionEnded,
    redirectUrl,
  }
}
