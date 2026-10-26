"use client"

import { useCallback, useEffect, useState } from "react"
import { Download, FileText, LoaderCircle, Play, RefreshCw, RotateCcw, Square } from "lucide-react"
import { downloadExperimentBundle, getExperimentConfig, getMeta, viewSessionReport } from "../../lib/admin-api"
import { cancelSyntheticBatch, getSyntheticBatches, startSyntheticBatch } from "../../lib/synthetic-api"
import type { ParticipantTraits, SyntheticBatch, SyntheticRequest } from "../../lib/synthetic-api"

const control = "w-full min-w-0 border border-admin-border rounded px-2.5 py-2 bg-admin-surface text-sm text-admin-text"
const tool = "inline-flex items-center justify-center w-8 h-8 shrink-0 rounded border border-admin-border text-admin-muted hover:bg-admin-raised disabled:opacity-40"
const active = (status: string) => status === "running" || status === "cancelling"
const label = (status: string) => status.replaceAll("_", " ")

export default function SyntheticTab({ adminKey, experimentId, sources }: { adminKey: string; experimentId: string; sources: string[] }) {
  const [sourceId, setSourceId] = useState(sources.includes(experimentId) ? experimentId : sources[0] || "")
  const [groups, setGroups] = useState<string[]>([])
  const [selectedGroups, setSelectedGroups] = useState<string[]>([])
  const [models, setModels] = useState<Record<string, string[]>>({})
  const [provider, setProvider] = useState("")
  const [model, setModel] = useState("")
  const [perGroup, setPerGroup] = useState(1)
  const [concurrency, setConcurrency] = useState(1)
  const [duration, setDuration] = useState(5)
  const [seed, setSeed] = useState(4200)
  const [seedMode, setSeedMode] = useState<"automatic" | "fixed">("automatic")
  const [stance, setStance] = useState<SyntheticRequest["stance"]>("seeded_balanced")
  const [profile, setProfile] = useState("Curious, with a clear opinion but willing to engage.")
  const [varyParticipants, setVaryParticipants] = useState(true)
  const [traits, setTraits] = useState<ParticipantTraits>({
    opinion_strength: "automatic", topic_knowledge: "automatic", style: "automatic", activity: "automatic",
  })
  const [intervalSeconds, setIntervalSeconds] = useState(45)
  const [maxCalls, setMaxCalls] = useState(20)
  const [confirmed, setConfirmed] = useState(false)
  const [batches, setBatches] = useState<SyntheticBatch[]>([])
  const [selectedBatch, setSelectedBatch] = useState("")
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [actionError, setActionError] = useState("")
  const total = perGroup * selectedGroups.length
  const hasActiveBatch = batches.some(b => active(b.status))
  const current = batches.find(b => b.batch_id === selectedBatch)

  const refresh = useCallback(async () => {
    try {
      setBatches(await getSyntheticBatches(adminKey))
      setError("")
    } catch (err) { setError(err instanceof Error ? err.message : "Could not load batches") }
  }, [adminKey])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setGroups([])
    setSelectedGroups([])
    setConfirmed(false)
    if (!sourceId) { setLoading(false); return }
    Promise.all([getExperimentConfig(adminKey, sourceId), getMeta(adminKey)])
      .then(([exp, meta]) => {
        if (cancelled) return
        const available = exp.config.synthetic ? [] : Object.keys(exp.config.experimental.groups)
        setGroups(available)
        setSelectedGroups(available)
        setModels(Object.fromEntries(Object.entries(meta.provider_models).map(([p, list]) => [p.toLowerCase(), list])))
        setProvider(exp.config.simulation.director_llm_provider.toLowerCase())
        setModel(exp.config.simulation.director_llm_model)
        setDuration(exp.config.simulation.session_duration_minutes)
      })
      .catch(err => { if (!cancelled) setActionError(err.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [adminKey, sourceId])

  useEffect(() => {
    refresh()
    const timer = setInterval(refresh, 3000)
    return () => clearInterval(timer)
  }, [refresh])

  async function launch() {
    setBusy(true)
    setActionError("")
    try {
      const batch = await startSyntheticBatch(adminKey, {
        source_experiment_id: sourceId, groups: selectedGroups, sessions_per_group: perGroup,
        concurrency, duration_minutes: duration, seed, seed_mode: seedMode, stance, participant_provider: provider,
        participant_model: model.trim(), participant_profile: profile,
        vary_participants: varyParticipants, participant_traits: traits,
        participant_interval_seconds: intervalSeconds, max_participant_calls: maxCalls,
        confirm_api_usage: confirmed,
      })
      setSelectedBatch(batch.batch_id)
      setConfirmed(false)
      await refresh()
    } catch (err) { setActionError(err instanceof Error ? err.message : "Could not start batch") }
    finally { setBusy(false) }
  }

  async function perform(action: () => Promise<unknown>) {
    setBusy(true)
    setActionError("")
    try { await action(); await refresh() }
    catch (err) { setActionError(err instanceof Error ? err.message : "Action failed") }
    finally { setBusy(false) }
  }

  return (
    <div className="space-y-6 text-admin-text">
      <header className="flex items-center justify-between gap-3">
        <h2 className="text-base font-semibold">Synthetic Sessions</h2>
        <button className={tool} title="Refresh batches" aria-label="Refresh batches" onClick={refresh}><RefreshCw size={15} /></button>
      </header>
      {(error || actionError) && <div role="alert" className="text-sm text-admin-danger-text bg-admin-danger-soft p-3 rounded break-words">{actionError || error}</div>}
      <form onSubmit={e => { e.preventDefault(); launch() }} className="border-y border-admin-border py-5 space-y-5">
        <label className="block text-xs space-y-1">Source experiment<select aria-label="Source experiment" disabled={busy || hasActiveBatch} className={control} value={sourceId} onChange={e => setSourceId(e.target.value)}>
          {sources.map(id => <option key={id} value={id}>{id}</option>)}
        </select></label>
        <fieldset disabled={loading || busy || hasActiveBatch || groups.length === 0} className="space-y-5 disabled:opacity-60">
          <legend className="text-xs font-semibold text-admin-muted mb-3">Batch Configuration</legend>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <label className="text-xs space-y-1 block">Sessions per treatment<input className={control} type="number" min={1} max={100} required value={perGroup} onChange={e => setPerGroup(Number(e.target.value))} /></label>
            <label className="text-xs space-y-1 block">Concurrent sessions<input className={control} type="number" min={1} max={4} required value={concurrency} onChange={e => setConcurrency(Number(e.target.value))} /></label>
            <label className="text-xs space-y-1 block">Duration (minutes)<input className={control} type="number" min={1} max={60} required value={duration} onChange={e => setDuration(Number(e.target.value))} /></label>
            <div className="space-y-2">
              <label className="text-xs space-y-1 block">Seed mode<select className={control} value={seedMode} onChange={e => setSeedMode(e.target.value as "automatic" | "fixed")}><option value="automatic">Automatic per batch</option><option value="fixed">Fixed</option></select></label>
              <label className="text-xs space-y-1 block">Base seed<input className={`${control} disabled:bg-admin-raised`} type="number" min={0} max={2147482647} required={seedMode === "fixed"} disabled={seedMode === "automatic"} placeholder="Automatic" value={seedMode === "fixed" ? seed : ""} onChange={e => setSeed(Number(e.target.value))} /></label>
            </div>
          </div>
          <fieldset>
            <legend className="text-xs text-admin-muted mb-2">Treatments</legend>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
              {groups.map(group => <label key={group} className="flex gap-2 items-start text-xs break-all">
                <input className="mt-0.5 shrink-0" type="checkbox" checked={selectedGroups.includes(group)} onChange={e => setSelectedGroups(e.target.checked ? [...selectedGroups, group] : selectedGroups.filter(g => g !== group))} />{group}
              </label>)}
            </div>
          </fieldset>
          <h3 className="text-sm font-semibold border-t border-admin-border pt-4">Synthetic Participant</h3>
          <label className="flex gap-2 items-start text-xs"><input type="checkbox" className="mt-0.5" checked={varyParticipants} onChange={e => setVaryParticipants(e.target.checked)} />Automatically vary participant profiles and response times</label>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            <label className="text-xs space-y-1 block">Provider<select className={control} value={provider} required onChange={e => { setProvider(e.target.value); setModel(models[e.target.value]?.[0] || "") }}>
              {Object.keys(models).map(p => <option key={p} value={p.toLowerCase()}>{p}</option>)}
            </select></label>
            <label className="text-xs space-y-1 block">Model<input className={control} list="synthetic-models" required maxLength={200} value={model} onChange={e => setModel(e.target.value)} /><datalist id="synthetic-models">{(models[provider] || []).map(m => <option key={m} value={m} />)}</datalist></label>
            <label className="text-xs space-y-1 block">Participant stance<select className={control} value={stance} onChange={e => setStance(e.target.value as SyntheticRequest["stance"])}><option value="seeded_balanced">Automatic, balanced pro / anti</option><option value="balanced">Alternating pro / anti, pro first</option><option value="pro_topic">Pro topic</option><option value="anti_topic">Anti topic</option></select></label>
            <label className="text-xs space-y-1 block">{varyParticipants ? "Base reaction interval (seconds)" : "Reaction interval (seconds)"}<input className={control} type="number" min={10} max={300} required value={intervalSeconds} onChange={e => setIntervalSeconds(Number(e.target.value))} /></label>
            <label className="text-xs space-y-1 block">Participant call cap / session<input className={control} type="number" min={1} max={100} required value={maxCalls} onChange={e => setMaxCalls(Number(e.target.value))} /></label>
          </div>
          <fieldset disabled={!varyParticipants} className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 disabled:opacity-50">
            <legend className="text-xs text-admin-muted mb-2">Participant traits</legend>
            <label className="text-xs space-y-1 block">Opinion strength<select className={control} value={traits.opinion_strength} onChange={e => setTraits({ ...traits, opinion_strength: e.target.value as ParticipantTraits["opinion_strength"] })}><option value="automatic">Automatic</option><option value="moderate">Moderate</option><option value="firm">Firm</option></select></label>
            <label className="text-xs space-y-1 block">Topic knowledge<select className={control} value={traits.topic_knowledge} onChange={e => setTraits({ ...traits, topic_knowledge: e.target.value as ParticipantTraits["topic_knowledge"] })}><option value="automatic">Automatic</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></label>
            <label className="text-xs space-y-1 block">Writing style<select className={control} value={traits.style} onChange={e => setTraits({ ...traits, style: e.target.value as ParticipantTraits["style"] })}><option value="automatic">Automatic</option><option value="brief">Brief</option><option value="conversational">Conversational</option><option value="argumentative">Argumentative</option></select></label>
            <label className="text-xs space-y-1 block">Participation level<select className={control} value={traits.activity} onChange={e => setTraits({ ...traits, activity: e.target.value as ParticipantTraits["activity"] })}><option value="automatic">Automatic</option><option value="observer">Observer</option><option value="regular">Regular</option><option value="active">Active</option></select></label>
          </fieldset>
          <label className="block text-xs space-y-1">{varyParticipants ? "Base participant profile" : "Participant profile"}<textarea className={`${control} min-h-20`} maxLength={2000} rows={2} value={profile} onChange={e => setProfile(e.target.value)} /></label>
          <label className="flex gap-2 items-start text-xs"><input type="checkbox" className="mt-0.5" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />I confirm the use of paid model APIs for this batch.</label>
        </fieldset>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-xs text-admin-muted">{total} sessions · {total * maxCalls} participant calls maximum</span>
          <button type="submit" disabled={loading || busy || hasActiveBatch || !confirmed || !model.trim() || total < 1 || total > 500} className="inline-flex items-center gap-2 px-4 py-2 bg-admin-accent text-white rounded text-sm disabled:opacity-40">
            {busy ? <LoaderCircle size={16} className="animate-spin" /> : <Play size={16} />}Start batch
          </button>
        </div>
      </form>
      <section className="space-y-3">
        <h3 className="text-sm font-semibold">Batches</h3>
        {batches.length === 0 ? <p className="text-sm text-admin-faint">No synthetic batches.</p> : <div className="overflow-x-auto">
          <table className="w-full text-xs text-left">
            <thead className="text-admin-faint"><tr><th className="py-2 pr-3">Batch</th><th className="pr-3">Source</th><th className="pr-3">Status</th><th className="pr-3">Finished</th><th className="pr-3">Messages</th><th className="w-20 relative"><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>{batches.map(batch => <tr key={batch.batch_id} className={`border-t border-admin-border ${selectedBatch === batch.batch_id ? "bg-admin-raised" : ""}`}>
              <td className="py-3 pr-3"><button className="underline font-mono" onClick={() => setSelectedBatch(batch.batch_id)}>{batch.batch_id.slice(0, 8)}</button></td>
              <td className="pr-3 break-all max-w-48">{batch.source_experiment_id}</td><td className="pr-3 capitalize">{label(batch.status)}</td>
              <td className="pr-3 tabular-nums">{batch.items.filter(i => !["queued", "running"].includes(i.status)).length}/{batch.items.length}</td>
              <td className="pr-3 tabular-nums">{batch.items.reduce((sum, i) => sum + i.messages, 0)}</td>
              <td><div className="flex gap-1">
                <button type="button" className={tool} title="Export synthetic experiment" aria-label="Export synthetic experiment" disabled={busy} onClick={() => perform(() => downloadExperimentBundle(adminKey, batch.experiment_id))}><Download size={14} /></button>
                {active(batch.status) && <button type="button" className={tool} title="Cancel batch" aria-label="Cancel batch" disabled={busy || batch.status === "cancelling"} onClick={() => perform(() => cancelSyntheticBatch(adminKey, batch.batch_id))}><Square size={14} /></button>}
              </div></td>
            </tr>)}</tbody>
          </table>
        </div>}
      </section>
      {current && <section className="space-y-3 border-t border-admin-border pt-4">
        <h3 className="text-sm font-semibold break-all">Batch {current.batch_id.slice(0, 8)}</h3>
        <p className="text-xs font-mono text-admin-muted break-all">{current.experiment_id}</p>
        <div className="flex flex-wrap items-center gap-2 text-xs text-admin-muted">
          <span className="tabular-nums">Base seed: {current.request.seed} ({current.request.seed_mode || "fixed"})</span>
          <button className={tool} title="Use this seed" aria-label="Use this seed" disabled={busy || hasActiveBatch} onClick={() => { setSeed(current.request.seed); setSeedMode("fixed") }}><RotateCcw size={14} /></button>
        </div>
        {current.error && <p className="text-sm text-admin-danger-text">{current.error}</p>}
        <div className="overflow-x-auto"><table className="w-full text-xs text-left"><thead className="text-admin-faint"><tr><th className="py-2 pr-3">Treatment</th><th className="pr-3">Seed / stance</th><th className="pr-3">Participant profile</th><th className="pr-3">Status</th><th className="pr-3">Messages</th><th className="pr-3">Participant calls</th><th className="pr-3">Outcome</th><th className="relative"><span className="sr-only">Report</span></th></tr></thead>
          <tbody>{current.items.map(item => <tr key={item.index} className="border-t border-admin-border"><td className="py-2 pr-3 break-all">{item.group}</td><td className="pr-3">{item.seed} / {item.stance === "pro_topic" ? "pro" : "anti"}</td><td className="pr-3 min-w-40"><details><summary className="cursor-pointer capitalize">{item.participant?.mode === "automatic" ? Object.values(item.participant.traits).join(" / ") : "Fixed profile"}</summary><p className="whitespace-pre-wrap py-2 max-w-72">{item.participant?.profile || current.request.participant_profile}</p>{item.participant && <p className="pb-2 text-admin-muted">{item.participant.interval_seconds}s{item.participant.jitter_fraction > 0 ? ` +/- ${item.participant.jitter_fraction * 100}%` : ""}</p>}</details></td><td className="pr-3 capitalize">{label(item.status)}</td><td className="pr-3">{item.messages}</td><td className="pr-3">{item.participant_calls}</td><td className="pr-3 max-w-64 break-words">{item.error || item.end_reason || "-"}</td><td>{item.session_id && <button className={tool} title="Open session report" aria-label="Open session report" onClick={() => perform(() => viewSessionReport(adminKey, item.session_id!))}><FileText size={14} /></button>}</td></tr>)}</tbody>
        </table></div>
      </section>}
    </div>
  )
}
