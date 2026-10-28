# Synthetic Sessions

The admin dashboard's **Synthetic** tab starts bounded batches using the selected
experiment as an immutable source. The participant has a separate provider,
model and profile; Director, Performer, Moderator, classifiers, pacing and safety
settings come from the source experiment. Session duration is an explicit override.

Each batch creates a paused `synthetic-<uuid>` experiment with no public entry
tokens. The source experiment, its tokens and its activation state are not changed.
Synthetic experiments cannot be activated for human entry. Their configuration
and session snapshots carry synthetic markers; standard exports and reports remain
available. Panel completion callbacks are disabled for synthetic experiments.

## Limits

- One batch can run platform-wide, protected by a PostgreSQL advisory lock.
- At most 500 sessions per batch and four concurrent sessions.
- No batch starts while human sessions are active or pending.
- The participant's API call cap is per session, including invalid/empty outputs.
  After that cap, it only listens until the session ends. This is **not** a total
  cost cap: agent, classifier and safety calls are additional.
- Sessions run at the source experiment's normal pace, not accelerated time.
- Stance, profiles and seeds are matched by replicate across treatments.
  Provider outputs are not guaranteed deterministic.
- Cancellation stops scheduling and tears down active sessions. API requests
  already accepted by a provider may still be billed.

The participant sees the news article and publicly delivered messages only, not
the treatment assignment, agent personas, internal evaluations or pending safety
messages. It can send a message/reply or wait. The same `handle_user_message`
path used by the real participant persists and screens its contributions.
No fake emotion or exit-survey responses are manufactured. A safety/operator
hold ends a synthetic run without automatically clearing the hold.

## Automatic Participant Variation

The admin form defaults to one session per treatment, automatic batch seeds,
automatic stance and automatic participant variation. With nine treatments this
creates nine sessions sharing the same assigned participant. Disable variation
for a fixed profile and fixed reaction interval. Older API requests without
`vary_participants` or `seed_mode` retain fixed behavior.

In automatic seed mode the server draws a new seed at launch, avoiding base seeds
already used by this source experiment. The resolved seed is saved in the batch
request and experiment snapshot and shown in batch details. Fixed mode accepts
an editable seed; the batch detail's **Use this seed** action fills it in. With
the same profile, trait settings and stance mode, that seed reproduces the
assignments and delay sequences. It does not reproduce model text. Distinct seeds
do not guarantee distinct profile combinations or conversations.

Automatic mode assigns opinion strength (moderate/firm), topic knowledge
(low/medium/high), style (brief/conversational/argumentative) and activity
(observer/regular/active). Each trait is shuffled in balanced blocks using the
base seed. Each trait can instead be fixed using the frontend selectors. These
overrides apply to every replicate; other traits keep their automatic assignment.
Attributes supplement the editable base profile; they do not assign anger,
incivility or a prescribed reaction to a treatment.

Automatic stance (`seeded_balanced`) draws the first stance using the resolved
seed, then alternates by replicate. Even replicate counts are equally pro/anti;
odd counts have one extra on the randomly selected starting side. A single
replicate can therefore be pro or anti, not always pro. Across independent batches
this is random, not a quota or forced alternation. The legacy alternating mode
(`balanced`) still starts pro. Explicit pro/anti settings never get randomized.

For climate experiments, stance follows the policy survey: prioritizing renewable
energy, environmental regulation and international CO2 targets versus prioritizing
energy costs and opposing those policies. It does not assign climate-change denial.

Each replicate reuses exactly the same profile and stance across all selected
treatments. Activity scales the base reaction interval by 1.4, 1.0 or 0.7,
respectively, with seeded +/-25% timing jitter per participant call. Delays remain
between 10 and 300 seconds. The initial reaction is immediate in both modes.
The API call cap is unchanged, and profile assignment uses no model calls.

Assignments are persisted before execution in the batch items, and in each
session's configuration snapshot and `synthetic_participant` event. Batch details
show expandable profiles. Seeds reproduce assignments and delay sequences, not
model responses or wall-clock delivery times. No demographic identities or
survey results are invented.

Synthetic initial posts use the same one-shot survey-side correction as human
posts. The assigned survey/profile is preserved; only a clear contradiction in
the first delivered post can change the locked effective treatment reference.
See [Participant Alignment](participant-alignment.md).

## Persistence and Restart

Batch progress is stored in `synthetic_batches` and survives browser reloads.
The additive schema is applied by the normal backend startup. If the worker
crashes, the next lock owner marks abandoned batches `interrupted` and closes
only their live synthetic sessions; it does not restart paid requests. Launch
a new batch to repeat an interrupted run. Normal shutdown cancels live batches.

## Troubleshooting

- Participant responses may be bare JSON or a single Markdown JSON code block.
  The same length, action and visible-reply checks apply in both cases. Truncated
  JSON, commentary surrounding the block and multiple blocks are not accepted.
- A participant message longer than 600 characters or a nonempty response with
  invalid JSON syntax gets one immediate repair opportunity, provided the
  per-session call cap has room. Syntax repairs request formatting changes only
  (for example, escaping internal quotes), preserving the message, action and
  reply target. Length repairs request a shorter message with the same meaning.
  The assigned opinion, profile, public context and normal input/safety path
  remain in force. Both error types **share one repair attempt**, not one each.
  Both calls count toward the same cap; messages are not silently truncated or
  sent over the limit. A `synthetic_participant_retry` event records the reason
  (`message_too_long` or `invalid_json`) and validation details. Valid JSON with
  an invalid action, blank content or an invisible reply target does not trigger
  a syntax repair. Empty/provider failures do not trigger this repair either.
  If the repair remains invalid, an initial reaction fails with the validation
  reason; a later contribution is skipped and the session continues listening.
- Director action retries include the rejection reason and the eligible speaker
  list for that turn. A session member visible in history may be a valid target
  without being eligible to speak now. This correction runs in the shared
  orchestrator for both human and synthetic sessions, with the same three-attempt
  limit and unchanged treatment, dimension, target and safety constraints.
- The source experiment's Director needs enough context for the full action
  prompt, including candidates, rules and conversation history. An HTTP 400 such
  as `request (10291 tokens) exceeds the available context size (8192 tokens)`
  is a server context limit, not a missing participant message. Select a Director
  with adequate context or have the provider increase the serving limit; retries
  do not make an oversized prompt fit. The runner does not silently truncate
  treatment or safety instructions or switch the source model.

Synthetic conversations are engineering tests, not evidence that human subjects
will react the same way. Dimension compliance still needs independent evaluation.
