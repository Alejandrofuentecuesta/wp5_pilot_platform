# Classifier Task

## Agent Context

{AGENT_IDEOLOGY}
Directly addresses participant: {ADDRESSES_PARTICIPANT}

## Recent Chat Context (last messages before the agent message)

{RECENT_CONTEXT}

## Participant Messages

{PARTICIPANT_MESSAGES}

## Agent Message To Classify

{AGENT_MESSAGE}

## Response

Return ONLY this JSON object:

```json
{
  "is_incivil": true|false,
  "is_like_minded": true|false|null,
  "stance_confidence": "high"|"medium"|"low"|null,
  "inferred_participant_stance": "short summary",
  "rationale": "one short sentence"
}
```
