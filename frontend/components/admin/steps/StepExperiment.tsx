"use client"

import { useEffect, useState } from "react"
import { listExperiments } from "../../../lib/admin-api"

interface StepExperimentProps {
  experimentId: string
  setExperimentId: (v: string) => void
  description: string
  setDescription: (v: string) => void
  startsAt: string
  setStartsAt: (v: string) => void
  endsAt: string
  setEndsAt: (v: string) => void
  redirectUrl: string
  setRedirectUrl: (v: string) => void
  adminKey: string
  isEditing?: boolean
}

export default function StepExperiment({
  experimentId,
  setExperimentId,
  description,
  setDescription,
  startsAt,
  setStartsAt,
  endsAt,
  setEndsAt,
  redirectUrl,
  setRedirectUrl,
  adminKey,
  isEditing = false,
}: StepExperimentProps) {
  const [existingIds, setExistingIds] = useState<Set<string>>(new Set())

  useEffect(() => {
    listExperiments(adminKey)
      .then((res) => {
        setExistingIds(new Set(res.experiments.map((e) => e.experiment_id)))
      })
      .catch(() => {})
  }, [adminKey])

  const isDuplicate = !isEditing && experimentId.trim() !== "" && existingIds.has(experimentId.trim())

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-admin-text">Experiment Identity</h2>
        <p className="text-sm text-admin-muted mt-1">
          Set a unique identifier for this experiment run. This will be applied to the backend when you save.
        </p>
      </div>

      <div className="bg-admin-surface rounded-lg border border-admin-border p-5 space-y-4">
        <div>
          <label htmlFor="exp-id" className="block text-sm font-medium text-admin-text mb-1">
            Experiment ID
          </label>
          <input
            id="exp-id"
            type="text"
            value={experimentId}
            onChange={(e) => setExperimentId(e.target.value)}
            placeholder="e.g. Bloque_1_Alejandro"
            disabled={isEditing}
            className={`w-full px-3 py-2 border rounded-lg text-sm bg-admin-surface text-admin-text focus:outline-none focus:ring-1 ${
              isDuplicate
                ? "border-red-400 focus:border-red-400 focus:ring-red-400/30"
                : "border-admin-border focus:border-admin-accent focus:ring-admin-accent/30"
            }`}
          />
          {isEditing ? (
            <p className="text-xs text-admin-faint mt-1">Experiment ID is locked while editing an existing experiment.</p>
          ) : isDuplicate ? (
            <p className="text-xs text-red-400 mt-1">
              An experiment with this ID already exists. Choose a different ID.
            </p>
          ) : (
            <p className="text-xs text-admin-faint mt-1">Used to isolate data in the database across experiment runs.</p>
          )}
        </div>

        <div>
          <label htmlFor="exp-desc" className="block text-sm font-medium text-admin-text mb-1">
            Description
          </label>
          <textarea
            id="exp-desc"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            placeholder="Brief description of this experiment run..."
            className="w-full px-3 py-2 border border-admin-border rounded-lg text-sm bg-admin-surface text-admin-text focus:outline-none focus:border-admin-accent focus:ring-1 focus:ring-admin-accent/30 resize-vertical"
          />
        </div>
      </div>

      <div className="bg-admin-surface rounded-lg border border-admin-border p-5 space-y-4">
        <div>
          <h3 className="text-sm font-semibold text-admin-text">Participation Window</h3>
          <p className="text-xs text-admin-muted mt-1">
            Participants can only use their tokens to start sessions within this time window.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label htmlFor="starts-at" className="block text-sm font-medium text-admin-text mb-1">
              Start Date &amp; Time
            </label>
            <input
              id="starts-at"
              type="datetime-local"
              value={startsAt}
              onChange={(e) => setStartsAt(e.target.value)}
              className="w-full px-3 py-2 border border-admin-border rounded-lg text-sm bg-admin-surface text-admin-text focus:outline-none focus:border-admin-accent focus:ring-1 focus:ring-admin-accent/30"
            />
          </div>
          <div>
            <label htmlFor="ends-at" className="block text-sm font-medium text-admin-text mb-1">
              End Date &amp; Time
            </label>
            <input
              id="ends-at"
              type="datetime-local"
              value={endsAt}
              onChange={(e) => setEndsAt(e.target.value)}
              className="w-full px-3 py-2 border border-admin-border rounded-lg text-sm bg-admin-surface text-admin-text focus:outline-none focus:border-admin-accent focus:ring-1 focus:ring-admin-accent/30"
            />
            {startsAt && endsAt && new Date(endsAt) <= new Date(startsAt) && (
              <p className="text-xs text-red-400 mt-1">End date must be after start date.</p>
            )}
          </div>
        </div>
      </div>

      <div className="bg-admin-surface rounded-lg border border-admin-border p-5 space-y-4">
        <div>
          <h3 className="text-sm font-semibold text-admin-text">Session Completion</h3>
          <p className="text-xs text-admin-muted mt-1">
            When a session ends (time limit reached), participants are redirected to this URL.
            If left empty, a built-in &quot;Thank you for participating&quot; page is shown instead.
          </p>
        </div>
        <div>
          <label htmlFor="redirect-url" className="block text-sm font-medium text-admin-text mb-1">
            Redirect URL (optional)
          </label>
          <input
            id="redirect-url"
            type="url"
            value={redirectUrl}
            onChange={(e) => setRedirectUrl(e.target.value)}
            placeholder="e.g. https://your-survey-tool.com/post-study-questionnaire"
            className="w-full px-3 py-2 border border-admin-border rounded-lg text-sm bg-admin-surface text-admin-text focus:outline-none focus:border-admin-accent focus:ring-1 focus:ring-admin-accent/30"
          />
        </div>
      </div>
    </div>
  )
}
