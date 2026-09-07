"use client"

import { useEffect } from "react"

interface BlockUserModalProps {
  senderName: string
  blocking: boolean
  onConfirm: () => void
  onClose: () => void
}

export default function BlockUserModal({
  senderName,
  blocking,
  onConfirm,
  onClose,
}: BlockUserModalProps) {
  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !blocking) onClose()
    }
    document.addEventListener("keydown", handleKey)
    return () => document.removeEventListener("keydown", handleKey)
  }, [blocking, onClose])

  return (
    <div
      className="fixed inset-0 z-[10000] flex items-center justify-center bg-black/40 px-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="block-user-title"
      onClick={(event) => {
        if (event.target === event.currentTarget && !blocking) onClose()
      }}
    >
      <div className="w-full max-w-[420px] overflow-hidden rounded-xl border border-border bg-white shadow-2xl">
        <div className="px-6 pb-4 pt-5">
          <h3 id="block-user-title" className="mb-2 text-lg font-semibold text-primary">
            ¿Bloquear a {senderName}?
          </h3>
          <p className="text-sm leading-relaxed text-secondary">
            Dejarás de ver sus mensajes y este usuario será sustituido en la conversación. Esta acción no se puede deshacer.
          </p>
        </div>
        <div className="flex justify-end gap-2 px-6 pb-5">
          <button
            type="button"
            onClick={onClose}
            disabled={blocking}
            className="rounded-lg border border-border px-4 py-2 text-sm text-secondary transition-colors hover:bg-gray-50 disabled:opacity-50"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={blocking}
            className="rounded-lg bg-danger px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-red-700 disabled:opacity-50"
          >
            {blocking ? "Bloqueando…" : "Bloquear usuario"}
          </button>
        </div>
      </div>
    </div>
  )
}
