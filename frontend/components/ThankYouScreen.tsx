"use client"

import { useEffect } from "react"

interface ThankYouScreenProps {
  redirectUrl: string | null
}

export default function ThankYouScreen({ redirectUrl }: ThankYouScreenProps) {
  useEffect(() => {
    if (redirectUrl) {
      const timer = setTimeout(() => {
        window.location.href = redirectUrl
      }, 2000)
      return () => clearTimeout(timer)
    }
  }, [redirectUrl])

  return (
    <div className="flex items-center justify-center h-dvh bg-bg-page">
      <div className="bg-bg-surface rounded-xl shadow-lg w-full max-w-sm mx-4 overflow-hidden border border-border">
        <div className="px-6 py-8 text-center">
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
                d="M20 6L9 17l-5-5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>
          <h1 className="text-xl font-semibold text-primary m-0">
            Thank you for participating!
          </h1>
          <p className="text-sm text-secondary mt-3">
            The discussion has ended. Your contributions have been recorded.
          </p>
          {redirectUrl && (
            <p className="text-xs text-tertiary mt-4">
              Redirecting you shortly...
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
