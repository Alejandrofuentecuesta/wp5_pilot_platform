/**
 * Tests for the alias boundary mapper — the privacy-critical seam that
 * keeps the typed name inside the browser. Run with `npm test`.
 */
import { describe, expect, it } from "vitest"

import { apparentGender, fold, isOwnSender, makeNameMapper, sanitizeName } from "./name"

describe("sanitizeName", () => {
  it("trims, collapses whitespace and strips control characters", () => {
    expect(sanitizeName("  María   José \n")).toBe("María José")
  })

  it("caps length at 60 characters", () => {
    expect(sanitizeName("a".repeat(100))).toHaveLength(60)
  })

  it("does not truncate to the first word", () => {
    expect(sanitizeName("María José García")).toBe("María José García")
  })
})

describe("fold", () => {
  it("is case- and accent-insensitive", () => {
    expect(fold("MARÍA José")).toBe("maria jose")
  })
})

describe("apparentGender", () => {
  it("matches compound names on the full string first", async () => {
    // Both orders have their own register entries with opposite genders.
    expect(await apparentGender("maría josé")).toBe("f")
    expect(await apparentGender("josé maría")).toBe("m")
  })

  it("falls back to the first word for name + surname", async () => {
    expect(await apparentGender("Lucía Fernández")).toBe("f")
  })

  it("falls back to the final-letter heuristic for unknown names", async () => {
    expect(await apparentGender("Zzyzka")).toBe("f")
    expect(await apparentGender("Zzyzko")).toBe("m")
  })

  it("returns null when nothing matches", async () => {
    expect(await apparentGender("Xyz")).toBeNull()
    expect(await apparentGender("   ")).toBeNull()
  })
})

describe("makeNameMapper", () => {
  const mapper = makeNameMapper("Marina", "María José")

  it("inbound rewrites the alias to the typed name", () => {
    expect(mapper.inbound("Marina tiene razón")).toBe("María José tiene razón")
  })

  it("inbound matches the alias accent- and case-insensitively", () => {
    expect(mapper.inbound("hola marína!")).toBe("hola María José!")
  })

  it("inbound leaves other words alone", () => {
    expect(mapper.inbound("la marinera llegó")).toBe("la marinera llegó")
  })

  it("outbound rewrites the typed multi-word name to the alias", () => {
    expect(mapper.outbound("soy María José y opino")).toBe("soy Marina y opino")
  })

  it("outbound matches the typed name without accents", () => {
    expect(mapper.outbound("soy maria jose")).toBe("soy Marina")
  })

  it("outbound does not match the phrase across punctuation", () => {
    expect(mapper.outbound("María. José vino")).toBe("María. José vino")
  })

  it("outbound does not match partial words", () => {
    expect(mapper.outbound("mariano habló de josefina")).toBe(
      "mariano habló de josefina",
    )
  })

  it("isAlias detects the alias sender, accent-insensitively", () => {
    expect(mapper.isAlias("Marina")).toBe(true)
    expect(mapper.isAlias("marína")).toBe(true)
    expect(mapper.isAlias("Lucía")).toBe(false)
  })

  it("is inert when alias or name is missing", () => {
    const empty = makeNameMapper("", "")
    expect(empty.inbound("Marina dice hola")).toBe("Marina dice hola")
    expect(empty.outbound("soy María")).toBe("soy María")
    expect(empty.isAlias("Marina")).toBe(false)
  })
})

describe("isOwnSender", () => {
  it("recognises the participant's alias, accent- and case-insensitively", () => {
    expect(isOwnSender("Óscar", "Óscar")).toBe(true)
    expect(isOwnSender("oscar", "Óscar")).toBe(true)
  })

  it("does not treat an agent who shares the typed name as the participant", () => {
    // Participant typed "Carlos" and runs under the alias "Hugo"; an agent
    // is called Carlos. Only the alias identifies the participant.
    expect(isOwnSender("Carlos", "Hugo")).toBe(false)
    expect(isOwnSender("Hugo", "Hugo")).toBe(true)
  })

  it("recognises the pre-alias placeholder sender", () => {
    expect(isOwnSender("participant", "")).toBe(true)
  })

  it("claims nothing before the alias is known", () => {
    expect(isOwnSender("Hugo", "")).toBe(false)
  })
})

describe("makeNameMapper with an agent sharing the typed name", () => {
  it("sends the name as written when an agent in the room has it", () => {
    const m = makeNameMapper("Hugo", "Carlos", ["Carlos", "Irene"])
    expect(m.outbound("Carlos, eso es mentira")).toBe("Carlos, eso es mentira")
  })

  it("matches the agent name accent- and case-insensitively", () => {
    const m = makeNameMapper("Hugo", "oscar", ["Óscar"])
    expect(m.outbound("oscar no tiene razón")).toBe("oscar no tiene razón")
  })

  it("still maps the typed name when no agent has it", () => {
    const m = makeNameMapper("Hugo", "Carlos", ["Irene"])
    expect(m.outbound("soy Carlos")).toBe("soy Hugo")
  })

  it("only exempts an exact match of the whole typed name", () => {
    const m = makeNameMapper("Hugo", "Carlos García", ["Carlos"])
    expect(m.outbound("soy Carlos García")).toBe("soy Hugo")
  })

  it("still maps the alias to the typed name inbound", () => {
    const m = makeNameMapper("Hugo", "Carlos", ["Carlos"])
    expect(m.inbound("Hugo tiene razón")).toBe("Carlos tiene razón")
  })
})

