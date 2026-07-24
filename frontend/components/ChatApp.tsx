"use client"

import { useEffect, useState } from "react"

import { useChat } from "@/hooks/useChat"
import LoginScreen, { type HandoffParams } from "./LoginScreen"
import ChatRoom from "./ChatRoom"
import IdleReminderBanner from "./IdleReminderBanner"
import ThankYouScreen from "./ThankYouScreen"
import QueueScreen from "./QueueScreen"
import type { ParticipantStance } from "@/lib/types"

function parseHandoffParams(): HandoffParams | null {
  const params = new URLSearchParams(window.location.search)
  const token = (params.get("token") || "").trim()
  if (!token) return null
  const s = (params.get("s") || "").trim()
  const stance: ParticipantStance | null =
    s === "1" ? "pro_topic" : s === "2" ? "anti_topic" : null
  return { token, stance }
}

export default function ChatApp() {
  const chat = useChat()
  const [handoff, setHandoff] = useState<HandoffParams | null>(null)
  const [bootChecked, setBootChecked] = useState(false)

  useEffect(() => {
    setHandoff(parseHandoffParams())
    setBootChecked(true)
  }, [])

  if (chat.sessionEnded) {
    return <ThankYouScreen redirectUrl={chat.redirectUrl} />
  }

  if (chat.queueToken && !chat.sessionId) {
    return (
      <QueueScreen
        position={chat.queuePosition}
        waitMinutes={chat.queueWaitMinutes}
        slotAvailable={chat.queueSlotAvailable}
        onPoll={chat.pollQueue}
        onClaim={chat.claimSlot}
        onExpired={chat.clearQueue}
      />
    )
  }

  if (!chat.sessionId) {
    // Wait one tick for the URL check so handoff arrivals never flash the
    // manual login screen.
    if (!bootChecked) return null

    return (
      <LoginScreen
        initialUsername={chat.username}
        handoff={handoff}
        onPreview={chat.previewSessionIntake}
        onStart={chat.startSession}
        onRejoin={chat.rejoinSession}
      />
    )
  }

  return (
    <>
      <IdleReminderBanner
        visible={chat.idlePromptVisible}
        onDismiss={chat.dismissIdlePrompt}
      />
      <ChatRoom
      visibleMessages={chat.visibleMessages}
      participants={chat.participants}
      displayName={chat.username}
      isConnected={chat.isConnected}
      inputValue={chat.inputValue}
      setInputValue={chat.setInputValue}
      replyTo={chat.replyTo}
      setReplyTo={chat.setReplyTo}
      sendMessage={chat.sendMessage}
      toggleLike={chat.toggleLike}
      reportModalOpen={chat.reportModalOpen}
      setReportModalOpen={chat.setReportModalOpen}
      reportTarget={chat.reportTarget}
      setReportTarget={chat.setReportTarget}
      reporting={chat.reporting}
      performReport={chat.performReport}
      typingCount={chat.typingCount}
      newsArticle={chat.newsArticle}
      newsArticleModalOpen={chat.newsArticleModalOpen}
      dismissNewsArticle={chat.dismissNewsArticle}
      openNewsArticle={chat.openNewsArticle}
      isInitialNewsRead={chat.isInitialNewsRead}
      submitInitialNewsMessage={chat.submitInitialNewsMessage}
      participantStance={chat.participantStance}
      emotionsCheckupOpen={chat.emotionsCheckupOpen}
      onSubmitEmotionsCheckup={chat.submitEmotionsCheckup}
      exitModalOpen={chat.exitModalOpen}
      setExitModalOpen={chat.setExitModalOpen}
      exitSession={chat.exitSession}
      />
    </>
  )
}
