/**
 * Participant name handling, entirely client-side.
 *
 * The typed name never leaves the browser: the backend receives only an
 * apparent-gender letter and assigns an alias, and this module maps between
 * the two at the network boundary. Gender is inferred from Spain's INE name
 * register (every first name with ≥20 bearers, compounds included), matched
 * on the full typed string first so compound first names like "María José"
 * resolve by their own register entry rather than their first word.
 */

const NAME_MAX_LEN = 60

export type ApparentGender = "m" | "f"

/** Trim, collapse whitespace, strip control characters, cap length. */
export function sanitizeName(raw: string): string {
  return raw
    .replace(/[\p{Cc}\p{Cf}]/gu, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, NAME_MAX_LEN)
    .trim()
}

/** Casefold and strip accents, mirroring the backend's fold(). */
export function fold(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
}

let genderMapPromise: Promise<Record<string, string>> | null = null

/** Kick off (and memoise) loading of the register-derived gender map. */
export function loadGenderMap(): Promise<Record<string, string>> {
  if (!genderMapPromise) {
    genderMapPromise = import("./name-genders.json").then(
      (mod) => mod.default as Record<string, string>,
    )
  }
  return genderMapPromise
}

/**
 * Best-effort apparent gender of a typed name: full-string register match,
 * then first word, then the Spanish final-letter heuristic, then null
 * (caller lets the backend pick either). Matching the full string first
 * matters: "JOSE MARIA" is male and "MARIA JOSE" is female, and both have
 * their own register entries.
 */
export async function apparentGender(name: string): Promise<ApparentGender | null> {
  const folded = fold(sanitizeName(name))
  if (!folded) return null
  const map = await loadGenderMap()

  const full = map[folded]
  if (full === "m" || full === "f") return full

  const firstWord = folded.split(" ")[0]
  const byFirst = map[firstWord]
  if (byFirst === "m" || byFirst === "f") return byFirst

  if (firstWord.endsWith("a")) return "f"
  if (firstWord.endsWith("o")) return "m"
  return null
}

/**
 * Bidirectional substitution between the typed name and the alias, applied
 * once at the WebSocket/API boundary. Inbound rewrites the alias back to
 * the typed name; outbound rewrites the typed name (as a whole phrase) to
 * the alias before a message leaves the browser, so even self-typed
 * "soy María José…" never reaches the backend verbatim. Matching is by
 * whole word, case- and accent-insensitive.
 */
export interface NameMapper {
  inbound: (text: string) => string
  outbound: (text: string) => string
  isAlias: (sender: string) => boolean
}

function replaceTokenSequence(
  text: string,
  targetWords: string[],
  replacement: string,
): string {
  if (targetWords.length === 0 || !text) return text
  const tokenRe = /[\p{L}](?:[\p{L}'’-])*/gu
  const tokens = Array.from(text.matchAll(tokenRe))
  const out: string[] = []
  let cursor = 0
  let i = 0
  while (i < tokens.length) {
    const window = tokens.slice(i, i + targetWords.length)
    const matches =
      window.length === targetWords.length &&
      window.every((tok, j) => fold(tok[0]) === targetWords[j]) &&
      // Consecutive tokens must be separated by whitespace only, so the
      // phrase "María José" doesn't match across punctuation.
      window.every((tok, j) =>
        j === 0
          ? true
          : /^\s+$/.test(text.slice(window[j - 1].index! + window[j - 1][0].length, tok.index!)),
      )
    if (matches) {
      const start = window[0].index!
      const end = window[window.length - 1].index! + window[window.length - 1][0].length
      out.push(text.slice(cursor, start), replacement)
      cursor = end
      i += targetWords.length
    } else {
      i += 1
    }
  }
  out.push(text.slice(cursor))
  return out.join("")
}

export function makeNameMapper(alias: string, typedName: string): NameMapper {
  const aliasWords = [fold(alias)]
  const typedWords = fold(sanitizeName(typedName)).split(" ").filter(Boolean)
  const display = sanitizeName(typedName)
  const usable = alias.length > 0 && typedWords.length > 0
  return {
    inbound: (text) =>
      usable ? replaceTokenSequence(text, aliasWords, display) : text,
    outbound: (text) =>
      usable ? replaceTokenSequence(text, typedWords, alias) : text,
    isAlias: (sender) => usable && fold(sender) === aliasWords[0],
  }
}
