import { useEffect, useRef, useState, useCallback } from "react"
import { WS_BASE } from "@/lib/constants"
import type { UserMessagePayload } from "@/lib/types"

interface UseWebSocketOptions {
  sessionId: string | null
  onMessage: (data: unknown) => void
  onSessionInvalid: () => void
}

export function useWebSocket({
  sessionId,
  onMessage,
  onSessionInvalid,
}: UseWebSocketOptions) {
  const [isConnected, setIsConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  // Use refs for callbacks to avoid re-creating the WebSocket on callback changes
  const onMessageRef = useRef(onMessage)
  const onSessionInvalidRef = useRef(onSessionInvalid)
  onMessageRef.current = onMessage
  onSessionInvalidRef.current = onSessionInvalid

  useEffect(() => {
    if (!sessionId) return
    let mounted = true
    let reconnectAttempts = 0
    let reconnectTimer: number | null = null

    const connect = () => {
      if (!mounted) return
      const ws = new WebSocket(`${WS_BASE}/ws/${sessionId}`)
      wsRef.current = ws

      ws.onopen = () => {
        setIsConnected(true)
        reconnectAttempts = 0
      }

      ws.onmessage = (event) => {
        try {
          const obj = JSON.parse(event.data)
          // Respond to server heartbeat pings.
          if (obj.type === "ping") {
            ws.send(JSON.stringify({ type: "pong" }))
            return
          }
          onMessageRef.current(obj)
        } catch (e) {
          console.error("Failed to parse WebSocket message:", e)
        }
      }

      ws.onclose = (event: CloseEvent) => {
        setIsConnected(false)

        if (event && (event.code === 1008 || event.code === 1011)) {
          onSessionInvalidRef.current()
          return
        }

        // Don't reconnect if the session ended normally.
        if (event && event.code === 1000 && event.reason === "session_ended") {
          return
        }

        if (reconnectAttempts < 5) {
          reconnectAttempts += 1
          reconnectTimer = window.setTimeout(
            connect,
            2000 * reconnectAttempts,
          )
        }
      }

      ws.onerror = (error) => {
        console.error("WebSocket error:", error)
      }
    }

    connect()

    return () => {
      mounted = false
      if (reconnectTimer) clearTimeout(reconnectTimer)
      if (wsRef.current) wsRef.current.close()
    }
  }, [sessionId])

  const send = useCallback((payload: UserMessagePayload) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(payload))
    }
  }, [])

  return { isConnected, send }
}
