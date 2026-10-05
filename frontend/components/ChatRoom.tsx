"use client"

import { useState, useEffect, useRef } from "react"
import type { Message, EmotionRating, MessageReaction } from "@/lib/types"
import ChatHeader from "./ChatHeader"
import MessageFeed from "./MessageFeed"
import InputBar from "./InputBar"
import ReportModal from "./ReportModal"
import NewsArticleModal from "./NewsArticleModal"
import EmotionsCheckupModal from "./EmotionsCheckupModal"
import ExitConfirmationModal from "./ExitConfirmationModal"
import BlockUserModal from "./BlockUserModal"
import type { ParticipantStance } from "@/lib/types"

interface ChatRoomProps {
  // Messages
  visibleMessages: Message[]
  participants: string[]
  displayName: string
  // Connection
  isConnected: boolean
  // Input
  inputValue: string
  // True while a researcher freeze is shown: nothing may be sent.
  inputDisabled?: boolean
  setInputValue: (v: string) => void
  // Reply
  replyTo: Message | null
  setReplyTo: (msg: Message | null) => void
  // Send
  sendMessage: (customContent?: string) => void
  // Like
  toggleLike: (msg: Message) => void
  toggleReaction: (msg: Message, reaction: MessageReaction) => void
  // Report
  reportModalOpen: boolean
  setReportModalOpen: (open: boolean) => void
  reportTarget: Message | null
  setReportTarget: (msg: Message | null) => void
  reporting: boolean
  performReport: (reasons: string[], otherReason: string | null) => void
  blockUser: (msg: Message) => void
  typingCount: number
  newsArticle: Message | null
  newsArticleModalOpen: boolean
  dismissNewsArticle: () => void
  openNewsArticle: () => void
  isInitialNewsRead?: boolean
  submitInitialNewsMessage?: (initialMessage: string) => void
  participantStance: ParticipantStance | null
  emotionsCheckupOpen: boolean
  emotionsCheckupIsShort?: boolean
  onSubmitEmotionsCheckup: (emotions: EmotionRating[], explanation: string) => void
  exitModalOpen: boolean
  openExitModal: () => void
  setExitModalOpen: (open: boolean) => void
  exitSession: (reason: string) => void
  onPasteBlocked?: (location: "chat_input" | "initial_reaction") => void
}

export default function ChatRoom({
  visibleMessages,
  participants,
  displayName,
  isConnected,
  inputValue,
  inputDisabled = false,
  setInputValue,
  replyTo,
  setReplyTo,
  sendMessage,
  toggleLike,
  toggleReaction,
  reportModalOpen,
  setReportModalOpen,
  reportTarget,
  setReportTarget,
  reporting,
  performReport,
  blockUser,
  typingCount,
  newsArticle,
  newsArticleModalOpen,
  dismissNewsArticle,
  openNewsArticle,
  isInitialNewsRead,
  submitInitialNewsMessage,
  participantStance,
  emotionsCheckupOpen,
  emotionsCheckupIsShort = true,
  onSubmitEmotionsCheckup,
  exitModalOpen,
  openExitModal,
  setExitModalOpen,
  exitSession,
  onPasteBlocked,
}: ChatRoomProps) {
  const [blockTarget, setBlockTarget] = useState<Message | null>(null)
  const [reportToastVisible, setReportToastVisible] = useState(false)
  const reportToastTimerRef = useRef<NodeJS.Timeout | null>(null)

  useEffect(() => {
    return () => {
      if (reportToastTimerRef.current) {
        clearTimeout(reportToastTimerRef.current)
      }
    }
  }, [])

  const handleReportAccept = (reasons: string[], otherReason: string | null) => {
    performReport(reasons, otherReason)
    if (reportToastTimerRef.current) {
      clearTimeout(reportToastTimerRef.current)
    }
    setReportToastVisible(true)
    reportToastTimerRef.current = setTimeout(() => {
      setReportToastVisible(false)
    }, 4000)
  }

  return (
    <div className="fixed inset-0 mx-auto flex h-dvh w-full max-w-3xl flex-col overflow-hidden overscroll-none bg-bg-surface shadow-lg">
      <ChatHeader
        participantCount={participants.length}
        isConnected={isConnected}
        onExitClick={openExitModal}
      />

      {/* Toast de confirmación de reporte */}
      {reportToastVisible && (
        <div
          role="status"
          aria-live="polite"
          className="absolute top-16 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2.5 px-4 py-2.5 rounded-full bg-gray-900/90 text-white shadow-xl backdrop-blur-sm border border-white/10 animate-in fade-in slide-in-from-top-3 duration-200 pointer-events-auto"
        >
          <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-500/20 text-emerald-400">
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <span className="text-xs sm:text-sm font-medium tracking-wide">
            Gracias, revisaremos este mensaje
          </span>
          <button
            type="button"
            onClick={() => {
              if (reportToastTimerRef.current) clearTimeout(reportToastTimerRef.current)
              setReportToastVisible(false)
            }}
            className="ml-1 text-gray-400 hover:text-white p-0.5 rounded-full transition-colors"
            aria-label="Cerrar notificación"
          >
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      )}

      <MessageFeed
        messages={visibleMessages}
        displayName={displayName}
        typingCount={typingCount}
        onReply={(msg) => setReplyTo(msg)}
        onLike={(msg) => toggleLike(msg)}
        onReaction={toggleReaction}
        onMention={(sender) => setInputValue(inputValue + `@${sender} `)}
        onReport={(msg) => {
          if (reporting) return
          setReportTarget(msg)
          setReportModalOpen(true)
        }}
        onBlock={setBlockTarget}
        onArticleClick={newsArticle ? openNewsArticle : undefined}
      />

      <InputBar
        inputValue={inputValue}
        setInputValue={setInputValue}
        replyTo={replyTo}
        onCancelReply={() => setReplyTo(null)}
        onSend={sendMessage}
        disabled={inputDisabled}
        onPasteBlocked={() => onPasteBlocked?.("chat_input")}
      />

      {/* Report modal */}
      {reportModalOpen && reportTarget && (
        <ReportModal
          senderName={reportTarget.sender}
          reporting={reporting}
          onAccept={handleReportAccept}
          onClose={() => {
            setReportModalOpen(false)
            setReportTarget(null)
          }}
        />
      )}

      {blockTarget && (
        <BlockUserModal
          senderName={blockTarget.sender}
          blocking={reporting}
          onConfirm={() => {
            blockUser(blockTarget)
            setBlockTarget(null)
          }}
          onClose={() => setBlockTarget(null)}
        />
      )}

      {newsArticle && (
        <NewsArticleModal
          message={newsArticle}
          open={newsArticleModalOpen}
          onClose={dismissNewsArticle}
          participantStance={participantStance}
          isInitialRead={isInitialNewsRead}
          onSubmitInitialMessage={submitInitialNewsMessage}
          isConnected={isConnected}
          onPasteBlocked={() => onPasteBlocked?.("initial_reaction")}
        />
      )}

      {/* Emotions checkup popup */}
      {emotionsCheckupOpen && (
        <EmotionsCheckupModal
          onSubmit={onSubmitEmotionsCheckup}
          isShort={emotionsCheckupIsShort}
        />
      )}

      {exitModalOpen && (
        <ExitConfirmationModal
          onConfirm={exitSession}
          onClose={() => setExitModalOpen(false)}
        />
      )}
    </div>
  )
}
