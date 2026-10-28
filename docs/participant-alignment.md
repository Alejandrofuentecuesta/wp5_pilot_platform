# Participant Alignment

The survey parameter (`participant_stance`) remains the original research datum.
Before agents can speak, the first participant post gets one local, deterministic
check for an explicit topic-side statement contradicting that survey. Only a
clear opposite side replaces the treatment reference. The treatment group itself
does not change.

Rules and prompts live in `backend/utils/participant_alignment.py`. They use
the fast classifier model (`classifier_llm`, typically Claude Haiku) with a
structured annotation prompt specific to the seed's `template_id`
(`immigration` or `climate_change`). If the model is unavailable or fails, the
survey stance is preserved without alteration. Unknown topics, generic reactions
to the article, questions, quotations, reported speech, uncertainty and mixed
signals abstain. This deliberately avoids false corrections while reliably
capturing natural Spanish phrasing and informal expressions. Climate rules concern
energy and environmental policy, not belief in climate science alone. A greeting
counts as the first post and exhausts this opportunity.

The decision is locked even if no correction is made. Later posts, Director
retries, reconnections and restarts never reconsider it. If the survey side is
missing, the same first-post rules may supply a side; otherwise it stays unknown.
The existing requirement to supply the pre-chat survey before agents start is
unchanged.

The first post's server-generated `participant_alignment_resolution` metadata
stores version, first message ID, original survey, inferred/effective sides,
source, matched rule identifiers and lock. It is persisted with the message and
included in normal exports. A corresponding event makes the decision auditable.
No new database migration or external classifier is needed.

Pool selection is rebuilt against a corrected side before any agent turn. All
parallel pipelines, Director references, Performer targeting constraints and
structural compliance counts use that same locked side. Original survey values
are not overwritten. Assigned agent sides remain immutable.

Recovery reads the saved decision from the first participant post, without
re-running the rules. Existing sessions lacking that metadata retain their
previous behavior; they are not retroactively corrected. Synthetic sessions use
the same input path: their assigned profile and survey are preserved, while a
clear contradiction in their generated initial post can correct the effective
side just as for a human participant.
