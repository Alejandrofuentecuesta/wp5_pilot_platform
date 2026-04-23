"use client"

import { useState, useCallback } from "react"

interface LoginScreenProps {
  initialUsername: string
  onStart: (token: string, username: string) => Promise<void>
}

export default function LoginScreen({
  initialUsername,
  onStart,
}: LoginScreenProps) {
  const [token, setToken] = useState("")
  const [username, setUsername] = useState(initialUsername)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  const handleSubmit = useCallback(async () => {
    if (!token.trim()) {
      setError("Please enter a token")
      return
    }
    setLoading(true)
    setError("")
    try {
      await onStart(token.trim(), username.trim())
    } catch {
      setError("Invalid token. Please try again.")
      setLoading(false)
    }
  }, [token, username, onStart])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <div className="flex items-center justify-center h-dvh bg-bg-page">
      <div className="bg-bg-surface rounded-xl shadow-lg w-full max-w-sm mx-4 overflow-hidden border border-border">
        {/* Card header */}
        <div className="px-6 pt-6 pb-4 text-center">
          <div className="w-12 h-12 rounded-xl bg-accent-soft mx-auto mb-3 flex items-center justify-center">
            <svg
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className="text-accent"
              aria-hidden="true"
            >
              <path
                d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>
          <h1 className="text-xl font-semibold text-primary m-0">
            Discussion Room
          </h1>
          <p className="text-sm text-secondary mt-1">
            Enter your token to join the discussion
          </p>
          <p className="text-xs text-secondary mt-2 leading-5 max-w-xs mx-auto">
            After you enter, you will read the article in a pop-up and choose whether you are in favor of the measure,
            against the measure, or in favor of the topic but against the measure. That self-report is used as a hint for
            agent selection in <span className="font-medium">agent-based</span> mode.
          </p>
        </div>

        {/* Form */}
        <div className="px-6 pb-6 space-y-3">
          <div>
            <label
              htmlFor="username"
              className="block text-xs font-medium text-secondary mb-1"
            >
              Display name (optional)
            </label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="e.g. Alice"
              className="w-full px-3 py-2.5 border border-border rounded-lg text-sm text-primary focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/30 transition-colors placeholder:text-tertiary bg-bg-surface"
            />
          </div>
          <div>
            <label
              htmlFor="token"
              className="block text-xs font-medium text-secondary mb-1"
            >
              Participant token
            </label>
            <input
              id="token"
              type="text"
              value={token}
              onChange={(e) => {
                setToken(e.target.value)
                if (error) setError("")
              }}
              onKeyDown={handleKeyDown}
              placeholder="e.g. user0002"
              className="w-full px-3 py-2.5 border border-border rounded-lg text-sm text-primary focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/30 transition-colors placeholder:text-tertiary bg-bg-surface"
              autoFocus
            />
          </div>

          {error && <p className="text-sm text-danger mt-1">{error}</p>}

          <button
            onClick={handleSubmit}
            disabled={loading}
            className="w-full py-2.5 bg-accent hover:bg-accent-hover text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50 mt-2"
          >
            {loading ? "Joining..." : "Join Discussion"}
          </button>
        </div>
      </div>
    </div>
  )
}
