# Classifier Task

Infer the participant's stance from the participant messages below and classify the agent message.

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
