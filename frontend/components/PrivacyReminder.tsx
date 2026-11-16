"use client"

interface PrivacyReminderProps {
  visible: boolean
  onConfirm: () => void
}

// Modal reminder shown when the participant's message contained personal
// data. The room is paused on the server until the participant confirms.
export default function PrivacyReminder({ visible, onConfirm }: PrivacyReminderProps) {
  if (!visible) return null

  return (
    <div
      className="fixed inset-0 z-[9998] flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm animate-in fade-in duration-200"
      role="dialog"
      aria-modal="true"
      aria-labelledby="privacy-reminder-title"
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
            <rect x="4" y="11" width="16" height="10" rx="2" />
            <path d="M8 11V7a4 4 0 0 1 8 0v4" />
          </svg>
        </div>

        <div className="space-y-1.5">
          <h3 id="privacy-reminder-title" className="text-xl font-semibold text-primary">
            Protege tu privacidad
          </h3>
          <p className="text-sm text-secondary leading-relaxed">
            Por favor, no compartas en el chat datos personales tuyos ni de otras personas, como
            nombres y apellidos, teléfonos, direcciones o correos electrónicos. Ese mensaje no se
            guardará.
          </p>
          <p className="text-sm text-secondary leading-relaxed">
            La conversación está en pausa hasta que pulses «Continuar».
          </p>
        </div>

        <button
          onClick={onConfirm}
          className="w-full rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold text-white shadow-md hover:bg-accent-hover transition-colors cursor-pointer mt-2"
        >
          Continuar
        </button>
      </div>
    </div>
  )
}
