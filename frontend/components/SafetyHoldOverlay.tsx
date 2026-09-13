"use client"

// Shown while a researcher has frozen the room from the admin panel. The
// participant learns only that the room is paused, never why; input is
// covered so nothing can be typed into a frozen room. Cleared by the
// server's resume event.
export default function SafetyHoldOverlay({ notice }: { notice: string | null }) {
  if (!notice) return null

  return (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm animate-in fade-in duration-200"
      role="dialog"
      aria-modal="true"
      aria-labelledby="safety-hold-title"
    >
      <div className="w-full max-w-sm rounded-2xl border border-border bg-bg-surface p-6 shadow-2xl flex flex-col items-center text-center space-y-4">
        <div className="w-12 h-12 rounded-full bg-accent-soft text-accent flex items-center justify-center shrink-0">
          <svg
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <rect x="6" y="4" width="4" height="16" />
            <rect x="14" y="4" width="4" height="16" />
          </svg>
        </div>
        <div className="space-y-1.5">
          <h3 id="safety-hold-title" className="text-xl font-semibold text-primary">
            Un momento
          </h3>
          <p className="text-sm text-secondary leading-relaxed">{notice}</p>
        </div>
      </div>
    </div>
  )
}
