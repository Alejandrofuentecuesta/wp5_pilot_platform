import { useState, useCallback, useMemo, useEffect, useRef } from "react"
import { useWebSocket } from "./useWebSocket"
import { useLocalStorage } from "./useLocalStorage"
import { useBehaviorTracking } from "./useBehaviorTracking"
import { PARTICIPANT_SENDER, LS_SESSION_ID, LS_USERNAME, LS_BLOCKED, LS_PARTICIPANT_STANCE } from "@/lib/constants"
import {
  previewSessionIntake as apiPreviewSessionIntake,
  startSession as apiStartSession,
  joinQueue as apiJoinQueue,
  likeMessage as apiLikeMessage,
  reactToMessage as apiReactToMessage,
  reportMessage as apiReportMessage,
  submitAgentImpressions as apiSubmitAgentImpressions,
  AtCapacityError,
} from "@/lib/api"
import { detectMentions } from "@/lib/mentions"
import { apparentGender, makeNameMapper, sanitizeName, type NameMapper } from "@/lib/name"
import type {
  Message,
  BlockedSenders,
  UserMessagePayload,
  LikeEvent,
  ReportEvent,
  ReactionEvent,
  BlockEvent,
  ParticipantStance,
  SessionIntakeResponse,
  AgentImpression,
  FinalReportBlockSurvey,
  MessageReaction,
  EmotionRating,
} from "@/lib/types"

function mergeUniqueNames(current: string[], additions: string[]) {
  const seen = new Set(current.map((name) => name.trim()).filter(Boolean))
  for (const name of additions) {
    const clean = name.trim()
    if (clean) seen.add(clean)
  }
  return Array.from(seen)
}

export function useChat() {
  // Session state
  const [sessionId, setSessionId] = useLocalStorage<string | null>(
    LS_SESSION_ID,
    null,
  )
  const [username, setUsername] = useLocalStorage<string>(LS_USERNAME, "")
  // The token this session was started with. Lets the boot logic tell a
  // page refresh (same token in the URL) apart from a NEW panel link that
  // must not be hijacked by a stale stored session.
  const [sessionToken, setSessionToken] = useLocalStorage<string | null>(
    "wp5_session_token",
    null,
  )
  const [participantStance, setParticipantStance] = useLocalStorage<ParticipantStance | null>(
    LS_PARTICIPANT_STANCE,
    null,
  )
  const blockedKey = sessionId ? `${LS_BLOCKED}:${sessionId}` : LS_BLOCKED
  const [blockedSenders, setBlockedSenders] = useLocalStorage<BlockedSenders>(
    blockedKey,
    {},
  )
  const surveyBlockedKey = sessionId
    ? `wp5_survey_blocked_agents:${sessionId}`
    : "wp5_survey_blocked_agents"
  const [surveyBlockedAgentNames, setSurveyBlockedAgentNames] = useLocalStorage<string[]>(
    surveyBlockedKey,
    [],
  )
  // The backend-assigned alias this session runs under. The typed name never
  // leaves the browser; the mapper below swaps the two at the boundary.
  const aliasKey = sessionId ? `alias:${sessionId}` : "alias"
  const [alias, setAlias] = useLocalStorage<string>(aliasKey, "")

  // Session end state
  const [sessionEnded, setSessionEnded] = useState(false)
  const [safetyIntervention, setSafetyIntervention] = useState(false)
  const [redirectUrl, setRedirectUrl] = useState<string | null>(null)
  // Reason the backend gave for session_end — used to decide whether the
  // deception debriefing must be shown before redirecting (researcher-
  // initiated early ends: safety_stop). Normal completion/self-exit rely on
  // the external survey's own debriefing page, as before.
  const [sessionEndReason, setSessionEndReason] = useState<string | null>(null)
  const [sessionAgentNames, setSessionAgentNames] = useState<string[]>([])
  const [agentImpressionSurveyOpen, setAgentImpressionSurveyOpen] = useState(false)
  const [agentImpressionsSubmitting, setAgentImpressionsSubmitting] = useState(false)
  const [agentImpressionsError, setAgentImpressionsError] = useState<string | null>(null)

  // Queue state (not persisted — refresh re-enters token which restores position)
  const [queueToken, setQueueToken] = useState<string | null>(null)
  const [queueName, setQueueName] = useState<string>("")
  const [queueStance, setQueueStance] = useState<ParticipantStance | null>(null)
  const [queuePosition, setQueuePosition] = useState(0)
  const [queueWaitMinutes, setQueueWaitMinutes] = useState(0)
  const [queueSlotAvailable, setQueueSlotAvailable] = useState(false)

  // Chat state
  const [messages, setMessages] = useState<Message[]>([])
  const [replyTo, setReplyTo] = useState<Message | null>(null)
  const [inputValue, setInputValue] = useState("")

  // Typing indicator state (count of agents currently typing)
  const [typingCount, setTypingCount] = useState(0)

  // Client-side behaviour config, delivered by the backend on WS attach.
  const [behaviorConfig, setBehaviorConfig] = useState({
    behaviorTrackingEnabled: false,
    idlePromptEnabled: false,
    idlePromptSeconds: 300,
  })

  // Report modal state
  const [reportModalOpen, setReportModalOpen] = useState(false)
  const [reportTarget, setReportTarget] = useState<Message | null>(null)
  const [reporting, setReporting] = useState(false)
  const [newsArticleModalOpen, setNewsArticleModalOpen] = useState(false)
  const [emotionsCheckupOpen, setEmotionsCheckupOpen] = useState(false)
  // Researcher hold (Safety tab): the room is frozen and the participant is
  // shown a neutral notice; only a server resume event clears it.
  const [safetyHoldNotice, setSafetyHoldNotice] = useState<string | null>(null)
  // The server reports on (re)connect that the room is idle-paused. A page
  // reload loses the local reminder, and only the participant can lift the
  // pause, so the reminder is shown again from this flag.
  const [serverIdlePaused, setServerIdlePaused] = useState(false)
  const [exitModalOpen, setExitModalOpen] = useState(false)
  const [isInitialNewsRead, setIsInitialNewsRead] = useState(false)
  const [initialMessageDone, setInitialMessageDone] = useState(false)

  // Derived: participants list from observed senders
  const participants = useMemo(() => {
    const set = new Set(
      messages.map((m) => m.sender).filter((s) => !s.startsWith("[")),
    )
    return [...set]
  }, [messages])

  const newsArticle = useMemo(
    () => messages.find((m) => m.msg_type === "news_article") || null,
    [messages],
  )

  const finalBlockedAgentNames = useMemo(
    () => mergeUniqueNames(surveyBlockedAgentNames, Object.keys(blockedSenders)),
    [surveyBlockedAgentNames, blockedSenders],
  )
  // Derived: detected mentions from current input
  const detectedMentions = useMemo(
    () => detectMentions(inputValue, participants),
    [inputValue, participants],
  )

  const usernameRef = useRef(username)
  useEffect(() => {
    usernameRef.current = username
  }, [username])

  // Boundary name mapper: inbound alias->typed name, outbound typed
  // name->alias. Held in a ref so the WS handler never goes stale.
  const mapperRef = useRef<NameMapper>(makeNameMapper("", ""))
  useEffect(() => {
    mapperRef.current = makeNameMapper(alias, username || alias)
  }, [alias, username])

  // Full conclusion of a session: nothing after this needs the typed name,
  // so it is removed from the browser along with the alias pairing, stance
  // and token — a shared device must not prefill the next visitor with the
  // previous participant's real name.
  const concludeSession = useCallback(() => {
    setAlias("")            // per-session key — must go before the id
    setUsername("")
    setParticipantStance(null)
    setSessionToken(null)
    setSessionId(null)
  }, [setAlias, setUsername, setParticipantStance, setSessionToken, setSessionId])

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
    } else if (obj && obj.event_type === "message_reaction") {
      const evt = obj as unknown as ReactionEvent
      setMessages((prev) =>
        prev.map((message) =>
          message.message_id === evt.message_id
            ? { ...message, reactions: evt.reactions }
            : message,
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
      const reason = typeof obj.reason === "string" ? obj.reason : "ended"
      const eventAgentNames = Array.isArray(obj.agent_names)
        ? obj.agent_names.filter(
            (name): name is string =>
              typeof name === "string" && name.trim().length > 0,
          )
        : []
      const feedbackAlreadySubmitted = Boolean(obj.agent_feedback_submitted)
      setSessionEndReason(reason)
      if (reason === "participant_safety") {
        setTypingCount(0)
        setRedirectUrl(url || null)
        setSafetyIntervention(true)
        setSessionEnded(false)
        setAgentImpressionSurveyOpen(false)
        // This is a terminal screen. Clear stored identity/session data while
        // retaining the in-memory return URL for its explicit exit button.
        concludeSession()
        return
      }
      setSessionEnded(true)
      setRedirectUrl(url || null)
      if (
        (reason === "duration_expired" || reason === "user_exit") &&
        sessionId &&
        eventAgentNames.length > 0 &&
        !feedbackAlreadySubmitted
      ) {
        setSessionAgentNames(eventAgentNames)
        setAgentImpressionSurveyOpen(true)
      } else {
        // Clear session so user can't refresh back into the chatroom.
        concludeSession()
      }
    } else if (obj && obj.event_type === "user_block") {
      const evt = obj as unknown as BlockEvent
      if (evt.blocked && typeof evt.blocked === "object") {
        setBlockedSenders(evt.blocked)
        setSurveyBlockedAgentNames((prev) => mergeUniqueNames(prev, Object.keys(evt.blocked)))
      }
    } else if (obj && obj.event_type === "emotions_checkup_trigger") {
      setEmotionsCheckupOpen(true)
    } else if (obj && obj.event_type === "session_paused") {
      if (obj.trigger === "hold") {
        setSafetyHoldNotice(typeof obj.notice === "string" && obj.notice ? obj.notice : "La sala está en pausa por un momento técnico. Volverá en breve.")
      }
    } else if (obj && obj.event_type === "session_resumed") {
      if (obj.trigger === "hold") setSafetyHoldNotice(null)
    } else if (obj && obj.event_type === "session_config") {
      if (obj.held) {
        setSafetyHoldNotice(typeof obj.hold_notice === "string" && obj.hold_notice ? obj.hold_notice : "La sala está en pausa por un momento técnico. Volverá en breve.")
      } else {
        setSafetyHoldNotice(null)
      }
      setServerIdlePaused(Boolean(obj.idle_paused))
      setBehaviorConfig({
        behaviorTrackingEnabled: Boolean(obj.behavior_tracking_enabled),
        idlePromptEnabled: Boolean(obj.idle_prompt_enabled),
        idlePromptSeconds: Number(obj.idle_prompt_seconds) || 300,
      })
      // Server-authoritative flag: on a rejoin from a fresh tab or device the
      // initial message was already posted, so the news form must not reappear.
      setInitialMessageDone(Boolean(obj.initial_message_done))
      // The alias anchors self-detection and the name mapping; on a fresh
      // device (no stored pairing) it also becomes the display name.
      if (typeof obj.user_name === "string" && obj.user_name) {
        setAlias(obj.user_name)
        setUsername((prev) => prev || (obj.user_name as string))
      }
    } else {
      const raw = obj as unknown as Message
      // Single ingress point for transcript content: the alias is rewritten
      // to the typed name here, so every component downstream renders the
      // participant's own name without further substitution.
      const mapper = mapperRef.current
      const message: Message = {
        ...raw,
        sender: mapper.isAlias(raw.sender) ? (usernameRef.current || raw.sender) : raw.sender,
        content: mapper.inbound(raw.content ?? ""),
        quoted_text: raw.quoted_text ? mapper.inbound(raw.quoted_text) : raw.quoted_text,
        mentions: Array.isArray(raw.mentions)
          ? raw.mentions.map((m) => (mapper.isAlias(m) ? (usernameRef.current || m) : m))
          : raw.mentions,
      }
      setMessages((prev) => {
        if (prev.some((m) => m.message_id === message.message_id)) {
          return prev
        }
        return [...prev, message]
      })
    }
  }, [sessionId, setBlockedSenders, setSurveyBlockedAgentNames, concludeSession, setAlias, setUsername])

  const handleSessionInvalid = useCallback(() => {
    setSessionId(null)
    alert(
      "La sesión no es válida o ha caducado. Vuelve a entrar desde tu enlace de participación.",
    )
  }, [setSessionId])

  const { isConnected, send } = useWebSocket({
    sessionId,
    onMessage: handleWSMessage,
    onSessionInvalid: handleSessionInvalid,
  })

  // The typing indicator is driven by paired typing_start/typing_stop
  // events; a disconnect can eat the stop and leave "someone is writing…"
  // stuck forever. Reset on every connection change — fresh events rebuild
  // the true state within a tick.
  useEffect(() => {
    setTypingCount(0)
  }, [isConnected])

  // Behavioural telemetry + idle "please write" reminder.
  const { track, trackImmediately, noteActivity, idlePromptVisible: idleReminderDue } =
    useBehaviorTracking({
      sessionId,
      trackingEnabled: behaviorConfig.behaviorTrackingEnabled,
      idleEnabled: behaviorConfig.idlePromptEnabled,
      idleSeconds: behaviorConfig.idlePromptSeconds,
      idleActive: initialMessageDone,
    })
  const idlePromptVisible = idleReminderDue || serverIdlePaused

  // Idle past the activity floor: tell the backend to freeze the simulation
  // so the participant does not miss exposure while the reminder is shown.
  // Sent when the reminder appears and again after every reconnect while it
  // is up (a send during a reconnect gap is dropped); the backend guards
  // against a repeat restarting its away-clock.
  useEffect(() => {
    if (idleReminderDue && isConnected) send({ type: "idle_pause" } as any)
  }, [idleReminderDue, isConnected, send])

  // Dismissing the reminder resumes the simulation and starts a fresh idle
  // window. noteActivity resets the idle clock and hides the reminder, so the
  // participant gets the full interval again before the next pause. If the
  // resume is lost to a reconnect gap, the server still reports the pause on
  // reconnect and the reminder comes back.
  const resumeFromIdle = useCallback(() => {
    send({ type: "resume" } as any)
    noteActivity()
    setServerIdlePaused(false)
  }, [send, noteActivity])

  // Per-message composition metrics (time spent typing, edit effort).
  const composeRef = useRef({ startedAt: 0, keystrokes: 0, backspaces: 0, pasted: false })

  // Wrap raw input changes so we can measure composition without plumbing key
  // events through InputBar. Deltas approximate typing effort.
  const handleInputChange = useCallback(
    (next: string) => {
      const prevLen = inputValue.length
      const nextLen = next.length
      const c = composeRef.current
      if (prevLen === 0 && nextLen > 0) {
        composeRef.current = { startedAt: Date.now(), keystrokes: 0, backspaces: 0, pasted: false }
      }
      const delta = nextLen - prevLen
      if (delta > 1) composeRef.current.pasted = true
      else if (delta === 1) composeRef.current.keystrokes += 1
      else if (delta < 0) composeRef.current.backspaces += 1
      // Typing does NOT reset the idle reminder — only posting a message does.
      setInputValue(next)
    },
    [inputValue],
  )

  useEffect(() => {
    if (!sessionId || !newsArticle || typeof window === "undefined") return
    const seenKey = `news_article_seen:${sessionId}`
    if (initialMessageDone) {
      // Rejoin: the server says the initial message was already posted. Mark
      // the article seen in this tab and close the form if it auto-opened
      // before the session_config event arrived.
      window.sessionStorage.setItem(seenKey, "1")
      if (isInitialNewsRead) {
        setIsInitialNewsRead(false)
        setNewsArticleModalOpen(false)
      }
      return
    }
    if (window.sessionStorage.getItem(seenKey) !== "1") {
      setIsInitialNewsRead(true)
      setNewsArticleModalOpen(true)
    }
  }, [sessionId, newsArticle, initialMessageDone, isInitialNewsRead])

  // Session intake preview (token validation + topic survey).
  const previewSessionIntake = async (
    token: string,
    panel?: { hkey?: string | null; g?: string | null },
  ): Promise<SessionIntakeResponse> => {
    return apiPreviewSessionIntake(token, panel)
  }

  const startSession = async (token: string, name: string, stance: ParticipantStance) => {
    const cleanName = sanitizeName(name)
    // Best effort only: a failure to load the gender map must never block
    // starting the session — the backend then picks an alias of either gender.
    let gender: "m" | "f" | null = null
    if (cleanName) {
      try {
        gender = await apparentGender(cleanName)
      } catch {
        gender = null
      }
    }
    try {
      const data = await apiStartSession(token, gender, stance)
      if (typeof window !== "undefined" && data.user_name) {
        // Persist under the new session's key before state catches up.
        window.localStorage.setItem(
          `alias:${data.session_id}`,
          JSON.stringify(data.user_name),
        )
      }
      setSessionId(data.session_id)
      setSessionToken(token)
      setAlias(data.user_name || "")
      if (cleanName) setUsername(cleanName)
      setParticipantStance(stance)
      setQueueToken(null)
      setSessionEnded(false)
      setSafetyIntervention(false)
      setRedirectUrl(null)
      setAgentImpressionSurveyOpen(false)
      setSessionAgentNames([])
    } catch (err) {
      const isCapacity = err instanceof AtCapacityError ||
        (err instanceof Error && err.message === "at_capacity")
      if (isCapacity) {
        try {
          const q = await apiJoinQueue(token, gender, stance)
          setQueueToken(token)
          setQueueName(name)
          setQueueStance(stance)
          setQueuePosition(q.position)
          setQueueWaitMinutes(q.estimated_wait_minutes)
          setQueueSlotAvailable(q.slot_available)
        } catch (joinErr) {
          console.error("[useChat] queue join failed:", joinErr)
          throw joinErr
        }
        return
      }
      throw err
    }
  }

  const pollQueue = async () => {
    if (!queueToken) return
    try {
      const q = await apiJoinQueue(queueToken)
      setQueuePosition(q.position)
      setQueueWaitMinutes(q.estimated_wait_minutes)
      setQueueSlotAvailable(q.slot_available)
    } catch (err) {
      if (err instanceof Error && (err.message.includes("401") || err.message.includes("403"))) {
        setQueueToken(null)
      }
    }
  }

  const claimSlot = async () => {
    if (!queueToken) return
    await startSession(queueToken, queueName, queueStance!)
  }

  const clearQueue = () => {
    setQueueToken(null)
    setQueuePosition(0)
    setQueueWaitMinutes(0)
    setQueueSlotAvailable(false)
  }

  // Reconnect to a still-alive session found via intake (used token whose
  // session is paused awaiting rejoin) — e.g. after cleared storage or on
  // another device.
  const rejoinSession = (id: string, token?: string) => {
    setSessionId(id)
    if (token) setSessionToken(token)
  }

  // Drop the stored session so the login/handoff flow takes over (used when
  // a NEW panel link must not be hijacked by a stale stored session).
  const clearSession = useCallback(() => {
    setSessionId(null)
  }, [setSessionId])

  // Send message
  const sendMessage = useCallback((customContent?: string): boolean => {
    const text = typeof customContent === "string" ? customContent.trim() : inputValue.trim()
    if (!text) return false
    // Nothing is sent into a room frozen by a researcher (safety hold or
    // paused experiment), whichever input it comes from.
    if (safetyHoldNotice) return false
    // Self-typed occurrences of the participant's own name travel as the
    // alias; the quoted text was inbound-mapped on arrival, so it is mapped
    // back before leaving.
    const content = mapperRef.current.outbound(text)
    const payload: UserMessagePayload = { type: "user_message", content }
    if (replyTo) {
      payload.reply_to = replyTo.message_id
      payload.quoted_text = mapperRef.current.outbound(replyTo.content)
    }
    if (detectedMentions.length > 0) payload.mentions = detectedMentions

    if (!send(payload)) return false

    // Record composition metrics for this message before clearing.
    const c = composeRef.current
    track("compose", {
      compose_ms: c.startedAt ? Date.now() - c.startedAt : 0,
      keystrokes: c.keystrokes,
      backspaces: c.backspaces,
      pasted: c.pasted,
      char_count: content.length,
    })
    composeRef.current = { startedAt: 0, keystrokes: 0, backspaces: 0, pasted: false }
    // Posting lifts an idle pause on the server too.
    noteActivity()
    setServerIdlePaused(false)

    setInputValue("")
    setReplyTo(null)
    return true
  }, [inputValue, replyTo, detectedMentions, send, track, noteActivity, safetyHoldNotice])

  const submitInitialNewsMessage = useCallback(
    (initialMessage: string) => {
      if (!sessionId) return
      // Only mark the article as seen and close the modal if the message
      // actually went out — a send during a reconnect gap is dropped, and
      // the session cannot start without this first message.
      if (!sendMessage(initialMessage)) return
      setInitialMessageDone(true)
      if (typeof window !== "undefined") {
        window.sessionStorage.setItem(`news_article_seen:${sessionId}`, "1")
      }
      setIsInitialNewsRead(false)
      setNewsArticleModalOpen(false)
    },
    [sessionId, sendMessage],
  )

  const dismissNewsArticle = useCallback(() => {
    if (sessionId && typeof window !== "undefined") {
      window.sessionStorage.setItem(`news_article_seen:${sessionId}`, "1")
    }
    setIsInitialNewsRead(false)
    setNewsArticleModalOpen(false)
  }, [sessionId])

  const openNewsArticle = useCallback(() => {
    setIsInitialNewsRead(false)
    setNewsArticleModalOpen(true)
  }, [])

  const submitEmotionsCheckup = useCallback((emotions: EmotionRating[], explanation: string) => {
    send({
      type: "emotions_checkup_response",
      // The free-text "other" emotion and explanation can contain the participant's own
      // name; predefined labels pass through the mapper unchanged.
      emotions: emotions.map((e) => ({
        ...e,
        emotion: mapperRef.current.outbound(e.emotion),
      })),
      emotion_explanation: mapperRef.current.outbound(explanation),
    } as any)
    setEmotionsCheckupOpen(false)
  }, [send])

  const openExitModal = useCallback(() => {
    trackImmediately("exit_attempt", { source: "chat_header" })
    setExitModalOpen(true)
  }, [trackImmediately])

  const exitSession = useCallback((reason: string) => {
    send({
      type: "user_exit",
      exit_reason: mapperRef.current.outbound(reason),
    } as any)
    setExitModalOpen(false)
  }, [send])

  const submitAgentImpressions = useCallback(
    async (ratings: AgentImpression[], finalReportBlockSurvey: FinalReportBlockSurvey) => {
      if (!sessionId) return
      setAgentImpressionsSubmitting(true)
      setAgentImpressionsError(null)
      try {
        const mappedSurvey: FinalReportBlockSurvey = {
          ...finalReportBlockSurvey,
          report_other: finalReportBlockSurvey.report_other
            ? mapperRef.current.outbound(finalReportBlockSurvey.report_other)
            : null,
          block_other: finalReportBlockSurvey.block_other
            ? mapperRef.current.outbound(finalReportBlockSurvey.block_other)
            : null,
        }
        await apiSubmitAgentImpressions(
          sessionId,
          ratings.map((r) => ({
            ...r,
            comment: r.comment ? mapperRef.current.outbound(r.comment) : r.comment,
          })),
          mappedSurvey,
        )
        setAgentImpressionSurveyOpen(false)
        // The comments above were the last thing that needed the outbound
        // name mapper — the typed name can now leave the browser.
        concludeSession()
      } catch {
        setAgentImpressionsError(
          "No se ha podido guardar la valoración. Inténtalo de nuevo.",
        )
      } finally {
        setAgentImpressionsSubmitting(false)
      }
    },
    [sessionId, concludeSession],
  )

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
      const data = await apiLikeMessage(sessionId, msg.message_id)
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

  const toggleReaction = async (msg: Message, reaction: MessageReaction) => {
    if (!sessionId) return
    const previous = { ...(msg.reactions || {}) }
    const next = { ...previous }
    if (next[PARTICIPANT_SENDER] === reaction) {
      delete next[PARTICIPANT_SENDER]
    } else {
      next[PARTICIPANT_SENDER] = reaction
    }
    setMessages((current) =>
      current.map((message) =>
        message.message_id === msg.message_id ? { ...message, reactions: next } : message,
      ),
    )

    try {
      const data = await apiReactToMessage(sessionId, msg.message_id, reaction)
      setMessages((current) =>
        current.map((message) =>
          message.message_id === data.message.message_id
            ? { ...message, reactions: data.message.reactions || {} }
            : message,
        ),
      )
    } catch {
      setMessages((current) =>
        current.map((message) =>
          message.message_id === msg.message_id ? { ...message, reactions: previous } : message,
        ),
      )
    }
  }

  // Report or block a message sender (with optimistic update + rollback).
  const reportOrBlock = async (
    target: Message,
    report: boolean,
    block: boolean,
    reasons: string[] = [],
    reasonOther: string | null = null,
  ) => {
    if (!sessionId || reporting) return
    setReporting(true)
    const uid = PARTICIPANT_SENDER
    const messageId = target.message_id
    const sender = target.sender

    // Prevent reporting or blocking yourself.
    if (sender === uid || sender === username) {
      setReporting(false)
      setReportModalOpen(false)
      setReportTarget(null)
      return
    }

    const prevReported = target.reported || false

    if (report) {
      setMessages((prev) =>
        prev.map((mm) =>
          mm.message_id === messageId ? { ...mm, reported: true } : mm,
        ),
      )
    }
    if (block) {
      const nowIso = new Date().toISOString()
      setBlockedSenders((prev) => {
        if (prev[sender]) return prev
        return { ...prev, [sender]: nowIso }
      })
      setSurveyBlockedAgentNames((prev) => mergeUniqueNames(prev, [sender]))
    }

    // The server may briefly wait for an in-flight agent turn before replacing
    // a blocked identity. The action is already reflected optimistically, so
    // close the modal now instead of leaving it disabled during that work.
    setReportModalOpen(false)
    setReportTarget(null)

    try {
      const data = await apiReportMessage(sessionId, messageId, {
        report,
        block,
        reasons,
        reason_other: reasonOther,
      })
      const serverMsg = data.message
      if (report) {
        setMessages((prev) =>
          prev.map((mm) =>
            mm.message_id === serverMsg.message_id
              ? { ...mm, reported: serverMsg.reported }
              : mm,
          ),
        )
      }
      if (data.blocked && typeof data.blocked === "object") {
        setBlockedSenders(data.blocked)
        setSurveyBlockedAgentNames((prev) => mergeUniqueNames(prev, Object.keys(data.blocked)))
      }
    } catch {
      if (report) {
        setMessages((prev) =>
          prev.map((mm) =>
            mm.message_id === messageId
              ? { ...mm, reported: prevReported }
              : mm,
          ),
        )
      }
      if (block) {
        setBlockedSenders((prev) => {
          const next = { ...prev }
          delete next[sender]
          return next
        })
        setSurveyBlockedAgentNames((prev) => prev.filter((name) => name !== sender))
      }
    } finally {
      setReporting(false)
    }
  }

  const performReport = async (reasons: string[], otherReason: string | null) => {
    if (!reportTarget) return
    await reportOrBlock(reportTarget, true, false, reasons, otherReason)
  }

  const blockUser = async (message: Message) => {
    await reportOrBlock(message, false, true)
  }
  // Filtered messages (respecting blocked senders)
  const visibleMessages = useMemo(() => {
    return messages.filter((msg) => {
      if (newsArticleModalOpen && msg.msg_type === "news_article") {
        return false
      }
      const blockedIso = blockedSenders[msg.sender]
      if (!blockedIso) return true
      try {
        return new Date(msg.timestamp) < new Date(blockedIso)
      } catch {
        return true
      }
    })
  }, [messages, blockedSenders, newsArticleModalOpen])

  return {
    // Session
    sessionId,
    sessionToken,
    clearSession,
    username,
    setUsername,
    participantStance,
    previewSessionIntake,
    startSession,
    // Connection
    isConnected,
    // Messages
    visibleMessages,
    participants,
    finalBlockedAgentNames,
    // Input
    inputValue,
    setInputValue: handleInputChange,
    detectedMentions,
    // Reply
    replyTo,
    setReplyTo,
    // Send
    sendMessage,
    // Like
    toggleLike,
    toggleReaction,
    // Report
    reportModalOpen,
    setReportModalOpen,
    reportTarget,
    setReportTarget,
    reporting,
    performReport,
    blockUser,
    newsArticle,
    newsArticleModalOpen,
    dismissNewsArticle,
    openNewsArticle,
    isInitialNewsRead,
    submitInitialNewsMessage,
    // Blocked
    blockedSenders,
    // Typing indicator
    typingCount,
    // Idle "please write in the chat" reminder
    idlePromptVisible,
    safetyHoldNotice,
    resumeFromIdle,
    // Session end
    sessionEnded,
    safetyIntervention,
    redirectUrl,
    sessionEndReason,
    sessionAgentNames,
    agentImpressionSurveyOpen,
    agentImpressionsSubmitting,
    agentImpressionsError,
    submitAgentImpressions,
    // Emotions Checkup
    emotionsCheckupOpen,
    submitEmotionsCheckup,
    // Exit
    exitModalOpen,
    openExitModal,
    setExitModalOpen,
    exitSession,
    // Queue
    queueToken,
    queuePosition,
    queueWaitMinutes,
    queueSlotAvailable,
    pollQueue,
    claimSlot,
    clearQueue,
    // Rejoin
    rejoinSession,
  }
}
