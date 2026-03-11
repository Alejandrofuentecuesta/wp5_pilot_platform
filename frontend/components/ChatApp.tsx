"use client"

import { useChat } from "@/hooks/useChat"
import LoginScreen from "./LoginScreen"
import ChatRoom from "./ChatRoom"
import ThankYouScreen from "./ThankYouScreen"

export default function ChatApp() {
  const chat = useChat()

  if (chat.sessionEnded) {
    return <ThankYouScreen redirectUrl={chat.redirectUrl} />
  }

  if (!chat.sessionId) {
    return (
      <LoginScreen
        initialUsername={chat.username}
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
    />
  )
}
