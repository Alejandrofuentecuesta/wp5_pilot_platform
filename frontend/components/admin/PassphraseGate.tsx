"use client"

import { useState, useCallback } from "react"
import { verifyPassphrase } from "../../lib/admin-api"
import type { AdminTheme } from "./AdminPanel"

interface PassphraseGateProps {
  onAuthenticated: (key: string) => void
  theme: AdminTheme
  onToggleTheme: () => void
}

export default function PassphraseGate({ onAuthenticated, theme, onToggleTheme }: PassphraseGateProps) {
  const [passphrase, setPassphrase] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  const handleSubmit = useCallback(async () => {
    if (!passphrase.trim()) {
      setError("Please enter the admin passphrase")
      return
    }
    setLoading(true)
    setError("")
    const verdict = await verifyPassphrase(passphrase.trim())
    if (verdict === "ok") {
      onAuthenticated(passphrase.trim())
    } else {
      setError(
        verdict === "throttled"
          ? "Too many failed attempts — wait 30 seconds and try again"
          : "Invalid passphrase",
      )
      setLoading(false)
    }
  }, [passphrase, onAuthenticated])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <div className="flex items-center justify-center h-dvh bg-admin-bg">
      {/* Decorative top band */}
      <div className="fixed top-0 left-0 right-0 h-32 bg-admin-accent-soft" />

      <div className="relative z-10 bg-admin-surface rounded-lg shadow-xl w-full max-w-sm mx-4 overflow-hidden border border-admin-border">
        <div className="bg-admin-accent-soft px-6 py-5 flex items-center justify-between">
          <div>
            <h1 className="text-admin-accent text-xl font-semibold m-0">
              Admin Panel
            </h1>
            <p className="text-admin-muted text-sm mt-1">
              Enter your passphrase to continue
            </p>
          </div>
          {/* Theme toggle */}
          <button
            onClick={onToggleTheme}
            className="p-1.5 rounded-lg bg-admin-surface/50 hover:bg-admin-surface text-admin-muted hover:text-admin-text transition-colors"
            aria-label={`Switch to ${theme === "light" ? "dark" : "light"} mode`}
            title={`Switch to ${theme === "light" ? "dark" : "light"} mode`}
          >
            {theme === "light" ? (
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
              </svg>
            )}
          </button>
        </div>

        <div className="px-6 py-5 space-y-3">
          <div>
            <label
              htmlFor="passphrase"
              className="block text-xs font-medium text-admin-muted mb-1"
            >
              Admin passphrase
            </label>
            <input
              id="passphrase"
              type="password"
              value={passphrase}
              onChange={(e) => {
                setPassphrase(e.target.value)
                if (error) setError("")
              }}
              onKeyDown={handleKeyDown}
              className="w-full px-3 py-2.5 border border-admin-border rounded-lg text-sm text-admin-text bg-admin-surface focus:outline-none focus:border-admin-accent focus:ring-1 focus:ring-admin-accent/30 transition-colors"
              autoFocus
            />
          </div>

          {error && (
            <p className="text-sm text-red-500 mt-1">{error}</p>
          )}

          <button
            onClick={handleSubmit}
            disabled={loading}
            className="w-full py-2.5 bg-admin-accent hover:bg-admin-accent-hover text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50 mt-2"
          >
            {loading ? "Verifying..." : "Enter"}
          </button>
        </div>
      </div>
    </div>
  )
}
