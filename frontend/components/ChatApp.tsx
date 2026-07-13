"use client"

import { useChat } from "@/hooks/useChat"
import LoginScreen from "./LoginScreen"
import ChatRoom from "./ChatRoom"
import ThankYouScreen from "./ThankYouScreen"
import QueueScreen from "./QueueScreen"

export default function ChatApp() {
  const chat = useChat()

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
    return (
      <LoginScreen
        initialUsername={chat.username}
        onPreview={chat.previewSessionIntake}
        onStart={chat.startSession}
      />
    )
  }

  return (
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
      participantStance={chat.participantStance}
      emotionsCheckupOpen={chat.emotionsCheckupOpen}
      onSubmitEmotionsCheckup={chat.submitEmotionsCheckup}
      exitModalOpen={chat.exitModalOpen}
      setExitModalOpen={chat.setExitModalOpen}
      exitSession={chat.exitSession}
    />
  )
}
