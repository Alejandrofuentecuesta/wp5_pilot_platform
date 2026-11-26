/** Minimum number of letters the participant's first message must contain. */
export const FIRST_MESSAGE_MIN_LETTERS = 3

/**
 * True when the first message has real text: at least FIRST_MESSAGE_MIN_LETTERS
 * letters (any alphabet, accents included). Blocks messages made only of
 * dots, symbols, digits or emoji, e.g. ".", "?", "123", "👍".
 */
export function isValidFirstMessage(text: string): boolean {
  const letters = text.match(/\p{L}/gu)
  return (letters?.length ?? 0) >= FIRST_MESSAGE_MIN_LETTERS
}
