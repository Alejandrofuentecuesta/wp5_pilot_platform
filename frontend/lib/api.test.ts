import { afterEach, describe, expect, it, vi } from "vitest"
import { previewSessionIntake } from "./api"

afterEach(() => vi.unstubAllGlobals())

function stubFetch() {
  const fetcher = vi.fn().mockResolvedValue(Response.json({ topic_template_id: "immigration", rejoin_session_id: null }))
  vi.stubGlobal("fetch", fetcher)
  return fetcher
}

function sentBody(fetcher: ReturnType<typeof vi.fn>): Record<string, string> {
  const init = fetcher.mock.calls[0][1] as RequestInit
  return JSON.parse(init.body as string)
}

describe("previewSessionIntake", () => {
  it("passes hkey, g and e from a panel link to the intake call", async () => {
    const fetcher = stubFetch()
    await previewSessionIntake("tok", { hkey: "abc", g: "7", e: "2" })
    expect(fetcher.mock.calls[0][0]).toMatch(/\/session\/intake$/)
    expect(sentBody(fetcher)).toEqual({ token: "tok", hkey: "abc", g: "7", e: "2" })
  })

  it("sends only the token for internally issued token links", async () => {
    const fetcher = stubFetch()
    await previewSessionIntake("tok")
    expect(sentBody(fetcher)).toEqual({ token: "tok" })
  })

  it("omits absent panel parameters rather than sending empty strings", async () => {
    const fetcher = stubFetch()
    await previewSessionIntake("tok", { hkey: "abc", g: null, e: null })
    expect(sentBody(fetcher)).toEqual({ token: "tok", hkey: "abc" })
  })
})
