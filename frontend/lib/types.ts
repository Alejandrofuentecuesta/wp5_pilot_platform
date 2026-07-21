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

export interface EmotionsCheckupResponsePayload {
  type: "emotions_checkup_response"
  emotion: string
  tempted_to_report: boolean
}

export type UserMessagePayload =
  | {
      type: "user_message"
      content: string
      reply_to?: string
      quoted_text?: string
      mentions?: string[]
    }
  | EmotionsCheckupResponsePayload

export interface SessionStartResponse {
  session_id: string
  message: string
}

export interface SessionIntakeResponse {
  topic_template_id: "climate_change" | "immigration"
  // Present when the token was already consumed but its session is still
  // alive (paused awaiting rejoin) — reconnect to it instead of starting.
  rejoin_session_id?: string | null
}

export type BlockedSenders = Record<string, string>

export type ParticipantStance =
  | "pro_topic"
  | "anti_topic"

export interface QueueJoinResponse {
  position: number
  estimated_wait_minutes: number
  slot_available: boolean
}
