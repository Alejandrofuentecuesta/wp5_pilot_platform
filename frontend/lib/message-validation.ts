export function isValidParticipantMessage(text: string): boolean {
  return (text.match(/[\p{L}\p{N}]/gu) || []).length >= 2
}

export const MESSAGE_VALIDATION_HINT = "Escribe algo m\u00e1s que una sola letra o s\u00edmbolo."
