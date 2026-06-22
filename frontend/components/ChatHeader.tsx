interface ChatHeaderProps {
  participantCount: number
  isConnected: boolean
  onExitClick?: () => void
}

export default function ChatHeader({
  participantCount,
  isConnected,
  onExitClick,
}: ChatHeaderProps) {
  return (
    <header className="flex items-center gap-3 px-4 py-3 bg-bg-surface border-b border-border shrink-0">
      {/* Discussion icon */}
      <div className="w-9 h-9 rounded-lg bg-accent-soft flex items-center justify-center shrink-0">
        <svg
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="text-accent"
          aria-hidden="true"
        >
          <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
        </svg>
      </div>
      <div className="flex-1 min-w-0">
        <h1 className="text-[15px] font-semibold text-primary leading-tight m-0">
          Discussion Room
        </h1>
        <p className="text-xs text-secondary leading-tight mt-0.5">
          {participantCount} participant{participantCount !== 1 ? "s" : ""}
        </p>
      </div>
      <div className="flex items-center gap-3 shrink-0">
        <div className="flex items-center gap-1.5">
          <div
            className={`w-2 h-2 rounded-full ${
              isConnected ? "bg-success animate-pulse" : "bg-danger"
            }`}
          />
          <span className="text-[11px] text-tertiary">
            {isConnected ? "Connected" : "Reconnecting"}
          </span>
        </div>
        {onExitClick && (
          <button
            onClick={onExitClick}
            className="px-2.5 py-1 text-xs border border-danger/35 hover:border-danger/60 bg-danger/5 hover:bg-danger/10 text-danger font-medium rounded-lg transition-colors cursor-pointer"
          >
            Exit
          </button>
        )}
      </div>
    </header>
  )
}
