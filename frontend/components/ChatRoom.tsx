"use client"

import type { Message } from "@/lib/types"
import ChatHeader from "./ChatHeader"
import MessageFeed from "./MessageFeed"
import InputBar from "./InputBar"
import ReportModal from "./ReportModal"
import NewsArticleModal from "./NewsArticleModal"
import EmotionsCheckupModal from "./EmotionsCheckupModal"
import ExitConfirmationModal from "./ExitConfirmationModal"
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
  setInputValue: (v: string) => void
  // Reply
  replyTo: Message | null
  setReplyTo: (msg: Message | null) => void
  // Send
  sendMessage: () => void
  // Like
  toggleLike: (msg: Message) => void
  // Report
  reportModalOpen: boolean
  setReportModalOpen: (open: boolean) => void
  reportTarget: Message | null
  setReportTarget: (msg: Message | null) => void
  reporting: boolean
  performReport: (block: boolean) => void
  typingCount: number
  newsArticle: Message | null
  newsArticleModalOpen: boolean
  dismissNewsArticle: () => void
  openNewsArticle: () => void
  participantStance: ParticipantStance | null
  emotionsCheckupOpen: boolean
  onSubmitEmotionsCheckup: (emotion: string, tempted: boolean, reportedUsers?: string[]) => void
  exitModalOpen: boolean
  setExitModalOpen: (open: boolean) => void
  exitSession: () => void
}

export default function ChatRoom({
  visibleMessages,
  participants,
  displayName,
  isConnected,
  inputValue,
  setInputValue,
  replyTo,
  setReplyTo,
  sendMessage,
  toggleLike,
  reportModalOpen,
  setReportModalOpen,
  reportTarget,
  setReportTarget,
  reporting,
  performReport,
  typingCount,
  newsArticle,
  newsArticleModalOpen,
  dismissNewsArticle,
  openNewsArticle,
  participantStance,
  emotionsCheckupOpen,
  onSubmitEmotionsCheckup,
  exitModalOpen,
  setExitModalOpen,
  exitSession,
}: ChatRoomProps) {
  return (
    <div className="flex flex-col h-dvh max-w-3xl mx-auto bg-bg-surface shadow-lg relative">
      <ChatHeader
        participantCount={participants.length}
        isConnected={isConnected}
        onExitClick={() => setExitModalOpen(true)}
      />

      <MessageFeed
        messages={visibleMessages}
        displayName={displayName}
        typingCount={typingCount}
        onReply={(msg) => setReplyTo(msg)}
        onLike={(msg) => toggleLike(msg)}
        onMention={(sender) => setInputValue(inputValue + `@${sender} `)}
        onReport={(msg) => {
          setReportTarget(msg)
          setReportModalOpen(true)
        }}
        onArticleClick={newsArticle ? openNewsArticle : undefined}
      />

      <InputBar
        inputValue={inputValue}
        setInputValue={setInputValue}
        replyTo={replyTo}
        onCancelReply={() => setReplyTo(null)}
        onSend={sendMessage}
      />

      {/* Report modal */}
      {reportModalOpen && reportTarget && (
        <ReportModal
          senderName={reportTarget.sender}
          reporting={reporting}
          onReport={() => performReport(false)}
          onReportAndBlock={() => performReport(true)}
          onClose={() => {
            setReportModalOpen(false)
            setReportTarget(null)
          }}
        />
      )}

      {newsArticle && (
        <NewsArticleModal
          message={newsArticle}
          open={newsArticleModalOpen}
          onClose={dismissNewsArticle}
          participantStance={participantStance}
        />
      )}

      {/* Emotions checkup popup */}
      {emotionsCheckupOpen && (
        <EmotionsCheckupModal
          onSubmit={onSubmitEmotionsCheckup}
          participants={participants.filter((p) => p !== displayName)}
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
