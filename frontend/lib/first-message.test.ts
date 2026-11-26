import { describe, expect, it } from "vitest"
import { isValidFirstMessage } from "./first-message"

describe("isValidFirstMessage", () => {
  it.each([".", "   ", "?", "...", "!!!", "123", "👍👍", "ok", ":)", "a."])("rejects %j", (text) => {
    expect(isValidFirstMessage(text)).toBe(false)
  })

  it.each(["hola", "Qué fuerte", "sí, ñoño", "No sé", "Uff 😮", "lol"])("accepts %j", (text) => {
    expect(isValidFirstMessage(text)).toBe(true)
  })
})
