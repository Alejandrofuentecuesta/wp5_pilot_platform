# Changelog

## [1.3.0] - 2026-03-10

### Upstream Merge: Session End Redirect + UX Improvements

Merged changes from the upstream repository ([what-if-horizon/wp5_pilot_platform](https://github.com/what-if-horizon/wp5_pilot_platform)) to align the codebase.

**What upstream changed:**

- **Completion redirect URL**: Experiments can now specify a URL to redirect participants to after their session ends (e.g. a Qualtrics survey). Configured in Step 1 of the wizard.
- **ThankYouScreen**: New post-session screen that shows "Thank you for participating!" and auto-redirects to the survey URL after 2 seconds.
- **Session end event via Redis**: Backend publishes a `session_end` event through Redis when a session expires or stops, including the `redirect_url`.
- **Sequential turns**: Upstream reverted from concurrent to sequential agent turns (`asyncio.Lock`) for research validity — each Director invocation sees all prior messages in order.
- **Crash recovery fix**: Session timer accuracy preserved on container restart via `_started_at` parameter passed to `SimulationSession`.
- **WebSocket reconnect fix**: Client no longer reconnects after a clean session-end close (code 1000, reason `session_ended`).

**Files replaced or merged:**
| File | Action |
|------|--------|
| `backend/platforms/chatroom.py` | Merged: added redirect_url, sequential turns, `_publish_session_end()` |
| `backend/utils/session_manager.py` | Replaced with upstream (crash recovery fix) |
| `frontend/components/ThankYouScreen.tsx` | New file from upstream |
| `frontend/components/ChatApp.tsx` | Replaced with upstream (shows ThankYouScreen on session end) |
| `frontend/hooks/useChat.ts` | Merged: added `sessionEnded` / `redirectUrl` state handling |
| `frontend/hooks/useWebSocket.ts` | Merged: added reconnect-on-clean-close fix |
| `frontend/lib/admin-types.ts` | Added `redirect_url` field to `ExperimentalConfig` |
| `frontend/components/admin/AdminPanel.tsx` | Added `redirect_url` default and wizard prop |
| `frontend/components/admin/steps/StepExperiment.tsx` | Added redirect URL input field |
| `frontend/components/admin/steps/StepReview.tsx` | Added "Completion redirect" review row |

---

## [1.2.0] - 2026-03-10

### New Feature: Clone Experiment

Added the ability to clone an existing experiment under a new ID, preserving the full configuration and generating fresh tokens.

- **Clone Experiment button** in Dashboard Overview tab (next to Edit Experiment)
- Opens a modal asking for the new experiment ID and optional description
- Copies simulation settings, LLM parameters, treatment groups, and classifier config
- Generates brand-new tokens (same group structure and counts, new values)
- Dashboard automatically switches to the cloned experiment after creation

**Files modified:**
| File | Changes |
|------|---------|
| `backend/main.py` | Added `POST /admin/experiment/{id}/clone` endpoint |
| `frontend/lib/admin-api.ts` | Added `cloneExperiment()` function |
| `frontend/components/admin/Dashboard.tsx` | Added Clone button, modal, and `onCloned` prop |

---

### New Feature: CSV Export for Comparison

Added a one-click CSV export of all session data for cross-experiment analysis.

- **Export CSV button** in the Sessions tab of the Dashboard
- One row per message including experiment parameters, session metadata, and classifier labels
- Columns: `experiment_id`, `description`, `director/performer/moderator/classifier model`, `session_duration_minutes`, `messages_per_minute`, `context_window_size`, `session_id`, `treatment_group`, `session_status`, `started_at`, `ended_at`, `end_reason`, `message_id`, `sender`, `sender_type` (participant/agent), `content`, `sent_at`, `is_incivil`, `is_like_minded`, `inferred_participant_stance`, `classification_rationale`, `reply_to`, `reported`
- Ideal for comparing different LLM models, prompts, and treatment approaches

**Files modified:**
| File | Changes |
|------|---------|
| `backend/main.py` | Added `GET /admin/sessions/csv/{experiment_id}` endpoint |
| `frontend/lib/admin-api.ts` | Added `downloadSessionsCSV()` function |
| `frontend/components/admin/Dashboard.tsx` | Added Export CSV button to Sessions tab |

---

### Classifier LLM — Implementation Audit

The classifier was already fully implemented. Summary of what exists:

- **Pipeline**: Runs as Stage 4 after Director → Performer → Moderator, before message storage
- **Classifies each agent message** on two dimensions:
  - `is_incivil`: true if message contains insults, contempt, or hostile tone
  - `is_like_minded`: true/false/null based on participant's inferred stance from their own messages
- **Stored** in dedicated DB columns (`is_incivil`, `is_like_minded`, `inferred_participant_stance`, `classification_rationale`)
- **Dashboard** shows `% Incivil` and `% Like-minded` per session in the Sessions tab
- **Configurable prompt** via the LLM step of the experiment wizard (Classifier section)
- **Separate LLM role** with its own provider, model, temperature, top_p, max_tokens settings

---

## [1.1.0] - 2026-03-10

### New Feature: Edit Experiment Button

Added the ability to edit existing experiments after creation, allowing researchers to modify parameters without recreating the entire experiment.

#### What's New

- **Edit Experiment Button** in Dashboard Overview tab
- Opens wizard with pre-loaded experiment configuration
- Modify simulation settings, LLM parameters, treatment groups, and schedule
- Experiment ID remains locked (cannot be changed after creation)
- Tokens are preserved when editing (no regeneration required)

#### Files Modified

| File | Changes |
|------|---------|
| `backend/main.py` | Added `PUT /admin/config/{experiment_id}` endpoint (lines 720-781), added PUT to CORS allowed methods (line 122) |
| `backend/db/repositories/config_repo.py` | Added `update_experiment_config()` function (lines 240-263) |
| `frontend/lib/admin-api.ts` | Added `updateConfig()` function (lines 94-114), updated `getExperimentConfig` return type |
| `frontend/components/admin/Dashboard.tsx` | Added `onEditExperiment` prop, added "Edit Experiment" button (lines 297-302) |
| `frontend/components/admin/AdminPanel.tsx` | Added edit mode state management, `handleEditExperiment` callback (lines 328-349) |
| `frontend/components/admin/steps/StepExperiment.tsx` | Added `isEditing` prop, disabled experiment ID when editing (lines 61, 68-69) |

#### Bug Fixes

- **CORS Error on PUT requests**: Fixed "Failed to fetch" error when saving edits by adding PUT to CORS allowed methods in `backend/main.py`

---

## How to Use

### Editing an Experiment

1. Go to the Admin Dashboard (`/admin`)
2. Select an experiment from the dropdown
3. In the Overview tab, click **"Edit Experiment"**
4. Modify any parameters in the wizard steps:
   - Step 1: Description and schedule (ID is locked)
   - Step 2: Session settings
   - Step 3: LLM configuration
   - Step 4: Treatment groups
   - Step 5: Tokens (skipped when editing)
   - Step 6: Review and save
5. Click **"Save"** to apply changes

### Important Notes

- Experiment ID cannot be changed after creation
- Existing tokens are preserved (no regeneration)
- LLM tests are auto-passed when editing (previously validated)
- Changes take effect immediately after saving

---

## Installation

```bash
git clone https://github.com/Alejandrofuentecuesta/wp5_pilot_platform.git
cd wp5_pilot_platform
docker compose up --build
```

Access the admin panel at: `http://localhost:3000/admin`

---

## [1.0.0] - Previous Fixes

### 1. Inconsistent Agent Personalities

**Problem:** Agents contradicted themselves and did not maintain coherent behavior during conversation.

**Cause:** The system only had agent names without defining individual personalities. The Director had no information to maintain consistency.

**Solution:**
- Added `persona` field to Agent model
- Modified Director prompt to include personalities
- Added UI in Admin Panel to define personalities per agent
- Explicit instruction to Director: "Maintain consistency - each agent should stay true to their personality traits"

**Files modified:**
- `backend/models/agent.py`
- `backend/agents/STAGE/director.py`
- `backend/platforms/chatroom.py`
- `frontend/lib/admin-types.ts`
- `frontend/components/admin/steps/StepSession.tsx`
- `frontend/components/admin/AdminPanel.tsx`

---

### 2. Tedious Experiment Configuration

**Problem:** All fields had to be filled manually each time, very slow for testing.

**Solution:** Pre-configured default values:
- 4 agents with defined names and personalities (Carlos, Maria, Pedro, Laura)
- 2x2 design already created (civil_pro, civil_against, incivil_pro, incivil_against)
- Pre-configured LLMs (Anthropic Director, HuggingFace Performer/Moderator)
- Pre-filled chatroom context

---

### 3. Uncensored Model for Uncivil Content

**Problem:** Models like Claude may refuse to generate very aggressive content.

**Solution:** Configured `dphn/Dolphin-Mistral-24B-Venice-Edition` as default Performer (uncensored model via HuggingFace/Featherless AI).

---

### 4. HuggingFace Token Not Loaded

**Problem:** Error "Cannot select auto-router when using non-Hugging Face API key"

**Cause:** Docker container did not reload environment variables with `docker compose restart`.

**Solution:** Use `docker compose up -d --force-recreate app` to force `.env` reload.

---

## Recommended LLM Configuration

| Role | Provider | Model | Reason |
|------|----------|-------|--------|
| Director | Anthropic | claude-sonnet-4-20250514 | Good at reasoning and deciding |
| Performer | HuggingFace | Dolphin-Mistral-24B:featherless-ai | Uncensored |
| Moderator | HuggingFace | Llama-3.1-8B-Instruct | Fast and cheap |

---

## Useful Commands

```bash
# Rebuild and launch
docker compose up -d --build

# View backend logs
docker compose logs app --tail=100

# Restart with new environment variables
docker compose up -d --force-recreate app
```
