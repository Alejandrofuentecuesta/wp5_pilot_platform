import { beforeEach, describe, expect, it, vi } from "vitest"
import { adminFetch } from "./admin-api"
import { cancelSyntheticBatch, getSyntheticBatches, startSyntheticBatch } from "./synthetic-api"
import type { SyntheticRequest } from "./synthetic-api"

vi.mock("./admin-api", () => ({ adminFetch: vi.fn() }))
const fetcher = vi.mocked(adminFetch)
const request: SyntheticRequest = {
  source_experiment_id: "source", groups: ["low"], sessions_per_group: 2,
  concurrency: 1, duration_minutes: 5, seed: 42, seed_mode: "automatic", stance: "seeded_balanced",
  participant_provider: "konstanz", participant_model: "model", participant_profile: "curious",
  vary_participants: true,
  participant_traits: { opinion_strength: "firm", topic_knowledge: "automatic", style: "brief", activity: "automatic" },
  participant_interval_seconds: 45, max_participant_calls: 20, confirm_api_usage: true,
}

beforeEach(() => fetcher.mockReset())

describe("synthetic API", () => {
  it("lists batches using admin authentication", async () => {
    fetcher.mockResolvedValue(Response.json({ batches: [{ batch_id: "one" }] }))
    expect(await getSyntheticBatches("key")).toEqual([{ batch_id: "one" }])
    expect(fetcher).toHaveBeenCalledWith("/admin/synthetic-batches", "key")
  })
  it("submits the explicit batch limits and confirmation", async () => {
    fetcher.mockResolvedValue(Response.json({ batch_id: "one" }, { status: 202 }))
    await startSyntheticBatch("key", request)
    expect(fetcher).toHaveBeenCalledWith("/admin/synthetic-batches", "key", {
      method: "POST", body: JSON.stringify(request),
    })
  })
  it("cancels only the requested batch", async () => {
    fetcher.mockResolvedValue(Response.json({ status: "cancelling" }))
    await cancelSyntheticBatch("key", "batch/id")
    expect(fetcher).toHaveBeenCalledWith("/admin/synthetic-batches/batch%2Fid/cancel", "key", { method: "POST" })
  })
  it("can explicitly keep a fixed participant profile", async () => {
    fetcher.mockResolvedValue(Response.json({ batch_id: "one" }, { status: 202 }))
    await startSyntheticBatch("key", { ...request, vary_participants: false })
    const options = fetcher.mock.calls[0][2] as RequestInit
    expect(JSON.parse(options.body as string).vary_participants).toBe(false)
  })
  it("submits an editable fixed seed and explicit stance", async () => {
    fetcher.mockResolvedValue(Response.json({ batch_id: "one" }, { status: 202 }))
    await startSyntheticBatch("key", { ...request, seed_mode: "fixed", seed: 12345, stance: "anti_topic" })
    const options = fetcher.mock.calls[0][2] as RequestInit
    expect(JSON.parse(options.body as string)).toMatchObject({ seed_mode: "fixed", seed: 12345, stance: "anti_topic" })
  })
  it("shows server conflicts", async () => {
    fetcher.mockResolvedValue(Response.json({ detail: "Human sessions are in progress" }, { status: 409 }))
    await expect(startSyntheticBatch("key", request)).rejects.toThrow("Human sessions are in progress")
  })
  it("handles structured validation errors", async () => {
    fetcher.mockResolvedValue(Response.json({ detail: [{ msg: "bad value" }] }, { status: 422 }))
    await expect(startSyntheticBatch("key", request)).rejects.toThrow("Request failed (422)")
  })
})
