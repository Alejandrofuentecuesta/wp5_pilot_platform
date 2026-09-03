export function formatMessageTime(isoString: string): string {
  const date = new Date(isoString)
  return date.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" })
}

export function getDateLabel(isoString: string): string {
  const date = new Date(isoString)
  const today = new Date()
  const yesterday = new Date(today)
  yesterday.setDate(yesterday.getDate() - 1)

  if (isSameDay(date, today)) return "Hoy"
  if (isSameDay(date, yesterday)) return "Ayer"
  return date.toLocaleDateString("es-ES", {
    day: "numeric",
    month: "long",
    year: "numeric",
  })
}

function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  )
}
