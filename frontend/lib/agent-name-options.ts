export const DEFAULT_AGENT_NAMES = [
  "Lucia",
  "Mateo",
  "Carmen",
  "Diego",
  "Sofia",
  "Javier",
  "Elena",
  "Pablo",
  "Marta",
  "Alvaro",
  "Nuria",
  "Adrian",
  "Claudia",
  "Sergio",
  "Irene",
  "Hector",
  "Paula",
  "Andres",
  "Laura",
  "Raul",
  "Aitana",
  "Daniel",
  "Noa",
  "Marcos",
  "Julia",
  "David",
  "Valeria",
  "Ivan",
  "Sara",
  "Gabriel",
  "Alba",
  "Hugo",
  "Carlota",
  "Bruno",
  "Cristina",
  "Alex",
  "Rocio",
  "Victor",
  "Natalia",
  "Mario",
  "Candela",
  "Ruben",
  "Eva",
  "Samuel",
  "Lidia",
  "Guillermo",
  "Ines",
  "Julian",
  "Patricia",
  "Dario",
  "Teresa",
  "Nicolas",
  "Bea",
  "Fernando",
  "Miriam",
  "Oscar",
  "Alicia",
  "Rodrigo",
  "Blanca",
  "Manuel",
] as const

function normalizeNameKey(name: string): string {
  return name.trim().toLowerCase()
}

function shuffleNames(names: readonly string[]): string[] {
  const shuffled = [...names]
  for (let i = shuffled.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]]
  }
  return shuffled
}

function getFallbackAgentName(used: Set<string>): string {
  let fallbackIndex = 1
  while (used.has(normalizeNameKey(`Agent ${fallbackIndex}`))) {
    fallbackIndex += 1
  }
  return `Agent ${fallbackIndex}`
}

export function normalizeAgentNames(count: number, existing: string[] = []): string[] {
  const names = existing.slice(0, count)
  const used = new Set(
    names
      .filter((name) => name.trim().length > 0)
      .map((name) => normalizeNameKey(name))
  )
  const shuffledPool = shuffleNames(DEFAULT_AGENT_NAMES)
  let poolIndex = 0

  while (names.length < count) {
    names.push("")
  }

  for (let i = 0; i < names.length; i += 1) {
    if (names[i].trim()) continue

    while (poolIndex < shuffledPool.length && used.has(normalizeNameKey(shuffledPool[poolIndex]))) {
      poolIndex += 1
    }

    const candidate =
      poolIndex < shuffledPool.length
        ? shuffledPool[poolIndex]
        : getFallbackAgentName(used)

    names[i] = candidate
    used.add(normalizeNameKey(candidate))
    if (poolIndex < shuffledPool.length) {
      poolIndex += 1
    }
  }

  return names
}

export function generateDefaultAgentNames(count: number): string[] {
  return normalizeAgentNames(count)
}
