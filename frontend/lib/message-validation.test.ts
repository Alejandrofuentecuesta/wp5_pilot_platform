import { describe, expect, it } from "vitest"
import { isValidParticipantMessage } from "./message-validation"

describe("participant message validation", () => {
  it.each(["", " ", "a", "?", "!!!", "a!", "\u{1f600}"])("rejects %s", (text) => {
    expect(isValidParticipantMessage(text)).toBe(false)
  })
  it.each(["hola", "s\u00ed", "no", "OK", "No estoy de acuerdo", "\u4f60\u597d"])("accepts %s", (text) => {
    expect(isValidParticipantMessage(text)).toBe(true)
  })
})
