export interface Message {
  sender: string
  content: string
  timestamp: string
  message_id: string
  reply_to?: string
  quoted_text?: string
  mentions?: string[]
  likes_count?: number
  liked_by?: string[]
  reported?: boolean
  // Feature seed messages (e.g. news articles)
  msg_type?: string
  headline?: string
  source?: string
  body?: string
}

export interface LikeEvent {
  event_type: "message_like"
  message_id: string
  likes_count: number
  liked_by: string[]
}

export interface ReportEvent {
  event_type: "message_report"
  message_id: string
  reported: boolean
}

export interface BlockEvent {
  event_type: "user_block"
  blocked: Record<string, string>
}

export type WSIncoming = Message | LikeEvent | ReportEvent | BlockEvent

export interface UserMessagePayload {
  type: "user_message"
  content: string
  reply_to?: string
  quoted_text?: string
  mentions?: string[]
}

export interface SessionStartResponse {
  session_id: string
  message: string
}

export interface SessionIntakeResponse {
  topic_template_id: "climate_change" | "immigration"
}

export type BlockedSenders = Record<string, string>

export type ParticipantStance =
  | "pro_topic"
  | "anti_topic"
