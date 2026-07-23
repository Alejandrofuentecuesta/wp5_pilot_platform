"use client"

interface IdleReminderBannerProps {
  visible: boolean
  onDismiss: () => void
}

// Modal reminder shown after a period of participant inactivity,
// nudging them to take part by writing in the chat with a blurred backdrop overlay.
export default function IdleReminderBanner({ visible, onDismiss }: IdleReminderBannerProps) {
  if (!visible) return null

  return (
    <div
      className="fixed inset-0 z-[9998] flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm animate-in fade-in duration-200"
      role="dialog"
      aria-modal="true"
      aria-labelledby="idle-reminder-title"
    >
      <div className="w-full max-w-sm rounded-2xl border border-border bg-bg-surface p-6 shadow-2xl animate-in zoom-in-95 duration-200 flex flex-col items-center text-center space-y-4">
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
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
        </div>

        <div className="space-y-1.5">
          <h3 id="idle-reminder-title" className="text-xl font-semibold text-primary">
            ¿Sigues ahí?
          </h3>
          <p className="text-sm text-secondary leading-relaxed">
            Recuerda que la discusión sigue activa.
          </p>
        </div>

        <button
          onClick={onDismiss}
          className="w-full rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold text-white shadow-md hover:bg-accent-hover transition-colors cursor-pointer mt-2"
        >
          Entendido
        </button>
      </div>
    </div>
  )
}
