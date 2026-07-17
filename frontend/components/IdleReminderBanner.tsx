"use client"

interface IdleReminderBannerProps {
  visible: boolean
  onDismiss: () => void
}

// Non-blocking reminder shown after a period of participant inactivity,
// nudging them to take part by writing in the chat.
export default function IdleReminderBanner({ visible, onDismiss }: IdleReminderBannerProps) {
  if (!visible) return null

  return (
    <div className="fixed inset-x-0 top-0 z-[9998] flex justify-center px-3 pt-3 pointer-events-none">
      <div className="pointer-events-auto flex items-center gap-3 rounded-xl bg-accent px-4 py-3 text-white shadow-lg animate-in fade-in slide-in-from-top-2 duration-200 max-w-md w-full">
        <span className="text-sm flex-1">
          Recuerda participar escribiendo un mensaje en el chat.
        </span>
        <button
          onClick={onDismiss}
          className="shrink-0 rounded-lg bg-white/20 px-2.5 py-1 text-xs font-semibold hover:bg-white/30 transition-colors"
          aria-label="Dismiss reminder"
        >
          OK
        </button>
      </div>
    </div>
  )
}
