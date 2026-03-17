import type { ExperimentalConfig, TreatmentGroup } from "./admin-types"

export const CHATROOM_CONTEXT_3X3 = `This is a Spanish-language chatroom on Telegram, based in Spain. Messages must be written in Spanish.
The participant has posted an opinion about a news article.
The Director must preserve the assigned treatment condition across the whole conversation.

Important design rule:
- Agents must remain ideologically consistent across the whole conversation.
- A like-minded agent should consistently support the participant.
- A not-like-minded agent should consistently oppose the participant.
- Do not switch an agent from support to opposition or from opposition to support.
- Treatment percentages refer to the share of total group messages across the conversation, not to changing agent beliefs.
- The Director should satisfy the treatment by choosing which consistent agents speak more or less often.
- Prefer stable speaking frequency per agent unless adjustment is needed to satisfy the treatment.
- Avoid abrupt over-correction in turn allocation.
- Keep the flow natural; do not force strict alternation.`

export const ECOLOGICAL_VALIDITY_3X3 = `Messages should stay short, natural, and chat-like.
The flow should feel like a real Telegram group conversation in Spanish.
Use a mix of standalone messages, replies, @mentions, and likes.
Keep turn-taking organic and avoid robotic alternation or obvious quota chasing.`

const GROUP_TREATMENTS: Record<string, string> = {
  low_against: `Maintain about 20% uncivil messages across the conversation.
Maintain about 20% like-minded messages and about 80% not-like-minded messages across the conversation.

Agent consistency:
- Agents must keep a stable position.
- Like-minded agents consistently support the participant.
- Not-like-minded agents consistently oppose the participant.
- The Director must meet the target by selecting who speaks more often, not by changing anyone's stance.
- Prefer approximately stable speaking frequency per agent unless adjustment is needed to satisfy the target percentages.
- Use mild, gradual turn-allocation corrections rather than abrupt swings.

Operational rule of thumb per 10 group messages:
- about 2 uncivil, about 8 civil;
- about 2 like-minded, about 8 not-like-minded.

Windowing rule:
- Stay close to the target not only overall, but also within any window of about 10 consecutive group messages.

Independence rule:
- Alignment and incivility are independent dimensions.
- A supportive message can be civil or uncivil.
- An opposing message can be civil or uncivil.

Style:
- Messages should remain short and natural.
- Uncivility means rudeness, sarcasm, mockery, or dismissive tone only.
- No slurs, no dehumanization, no threats, no incitement to violence.`,

  low_mixed: `Maintain about 20% uncivil messages across the conversation.
Maintain about 50% like-minded messages and about 50% not-like-minded messages across the conversation.

Agent consistency:
- Agents must keep a stable position.
- Like-minded agents consistently support the participant.
- Not-like-minded agents consistently oppose the participant.
- The Director must meet the target by selecting who speaks more often, not by changing anyone's stance.
- Prefer approximately stable speaking frequency per agent unless adjustment is needed to satisfy the target percentages.
- Use mild, gradual turn-allocation corrections rather than abrupt swings.

Operational rule of thumb per 10 group messages:
- about 2 uncivil, about 8 civil;
- about 5 like-minded, about 5 not-like-minded.

Windowing rule:
- Stay close to the target not only overall, but also within any window of about 10 consecutive group messages.

Independence rule:
- Alignment and incivility are independent dimensions.
- A supportive message can be civil or uncivil.
- An opposing message can be civil or uncivil.

Style:
- Messages should remain short and natural.
- Uncivility means rudeness, sarcasm, mockery, or dismissive tone only.
- No slurs, no dehumanization, no threats, no incitement to violence.`,

  low_favor: `Maintain about 20% uncivil messages across the conversation.
Maintain about 80% like-minded messages and about 20% not-like-minded messages across the conversation.

Agent consistency:
- Agents must keep a stable position.
- Like-minded agents consistently support the participant.
- Not-like-minded agents consistently oppose the participant.
- The Director must meet the target by selecting who speaks more often, not by changing anyone's stance.
- Prefer approximately stable speaking frequency per agent unless adjustment is needed to satisfy the target percentages.
- Use mild, gradual turn-allocation corrections rather than abrupt swings.

Operational rule of thumb per 10 group messages:
- about 2 uncivil, about 8 civil;
- about 8 like-minded, about 2 not-like-minded.

Windowing rule:
- Stay close to the target not only overall, but also within any window of about 10 consecutive group messages.

Independence rule:
- Alignment and incivility are independent dimensions.
- A supportive message can be civil or uncivil.
- An opposing message can be civil or uncivil.

Style:
- Messages should remain short and natural.
- Uncivility means rudeness, sarcasm, mockery, or dismissive tone only.
- No slurs, no dehumanization, no threats, no incitement to violence.`,

  medium_against: `Maintain about 50% uncivil messages across the conversation.
Maintain about 20% like-minded messages and about 80% not-like-minded messages across the conversation.

Agent consistency:
- Agents must keep a stable position.
- Like-minded agents consistently support the participant.
- Not-like-minded agents consistently oppose the participant.
- The Director must meet the target by selecting who speaks more often, not by changing anyone's stance.
- Prefer approximately stable speaking frequency per agent unless adjustment is needed to satisfy the target percentages.
- Use mild, gradual turn-allocation corrections rather than abrupt swings.

Operational rule of thumb per 10 group messages:
- about 5 uncivil, about 5 civil;
- about 2 like-minded, about 8 not-like-minded.

Windowing rule:
- Stay close to the target not only overall, but also within any window of about 10 consecutive group messages.

Independence rule:
- Alignment and incivility are independent dimensions.
- A supportive message can be civil or uncivil.
- An opposing message can be civil or uncivil.

Style:
- Messages should remain short and natural.
- Uncivility means rudeness, sarcasm, mockery, or dismissive tone only.
- No slurs, no dehumanization, no threats, no incitement to violence.`,

  medium_mixed: `Maintain about 50% uncivil messages across the conversation.
Maintain about 50% like-minded messages and about 50% not-like-minded messages across the conversation.

Agent consistency:
- Agents must keep a stable position.
- Like-minded agents consistently support the participant.
- Not-like-minded agents consistently oppose the participant.
- The Director must meet the target by selecting who speaks more often, not by changing anyone's stance.
- Prefer approximately stable speaking frequency per agent unless adjustment is needed to satisfy the target percentages.
- Use mild, gradual turn-allocation corrections rather than abrupt swings.

Operational rule of thumb per 10 group messages:
- about 5 uncivil, about 5 civil;
- about 5 like-minded, about 5 not-like-minded.

Windowing rule:
- Stay close to the target not only overall, but also within any window of about 10 consecutive group messages.

Independence rule:
- Alignment and incivility are independent dimensions.
- A supportive message can be civil or uncivil.
- An opposing message can be civil or uncivil.

Style:
- Messages should remain short and natural.
- Uncivility means rudeness, sarcasm, mockery, or dismissive tone only.
- No slurs, no dehumanization, no threats, no incitement to violence.`,

  medium_favor: `Maintain about 50% uncivil messages across the conversation.
Maintain about 80% like-minded messages and about 20% not-like-minded messages across the conversation.

Agent consistency:
- Agents must keep a stable position.
- Like-minded agents consistently support the participant.
- Not-like-minded agents consistently oppose the participant.
- The Director must meet the target by selecting who speaks more often, not by changing anyone's stance.
- Prefer approximately stable speaking frequency per agent unless adjustment is needed to satisfy the target percentages.
- Use mild, gradual turn-allocation corrections rather than abrupt swings.

Operational rule of thumb per 10 group messages:
- about 5 uncivil, about 5 civil;
- about 8 like-minded, about 2 not-like-minded.

Windowing rule:
- Stay close to the target not only overall, but also within any window of about 10 consecutive group messages.

Independence rule:
- Alignment and incivility are independent dimensions.
- A supportive message can be civil or uncivil.
- An opposing message can be civil or uncivil.

Style:
- Messages should remain short and natural.
- Uncivility means rudeness, sarcasm, mockery, or dismissive tone only.
- No slurs, no dehumanization, no threats, no incitement to violence.`,

  high_against: `Maintain about 80% uncivil messages across the conversation.
Maintain about 20% like-minded messages and about 80% not-like-minded messages across the conversation.

Agent consistency:
- Agents must keep a stable position.
- Like-minded agents consistently support the participant.
- Not-like-minded agents consistently oppose the participant.
- The Director must meet the target by selecting who speaks more often, not by changing anyone's stance.
- Prefer approximately stable speaking frequency per agent unless adjustment is needed to satisfy the target percentages.
- Use mild, gradual turn-allocation corrections rather than abrupt swings.

Operational rule of thumb per 10 group messages:
- about 8 uncivil, about 2 civil;
- about 2 like-minded, about 8 not-like-minded.

Windowing rule:
- Stay close to the target not only overall, but also within any window of about 10 consecutive group messages.

Independence rule:
- Alignment and incivility are independent dimensions.
- A supportive message can be civil or uncivil.
- An opposing message can be civil or uncivil.

Style:
- Messages should remain short and sharp.
- Uncivility means strong rudeness, repeated sarcasm, mockery, and harsh dismissiveness only.
- No slurs, no dehumanization, no threats, no incitement to violence.`,

  high_mixed: `Maintain about 80% uncivil messages across the conversation.
Maintain about 50% like-minded messages and about 50% not-like-minded messages across the conversation.

Agent consistency:
- Agents must keep a stable position.
- Like-minded agents consistently support the participant.
- Not-like-minded agents consistently oppose the participant.
- The Director must meet the target by selecting who speaks more often, not by changing anyone's stance.
- Prefer approximately stable speaking frequency per agent unless adjustment is needed to satisfy the target percentages.
- Use mild, gradual turn-allocation corrections rather than abrupt swings.

Operational rule of thumb per 10 group messages:
- about 8 uncivil, about 2 civil;
- about 5 like-minded, about 5 not-like-minded.

Windowing rule:
- Stay close to the target not only overall, but also within any window of about 10 consecutive group messages.

Independence rule:
- Alignment and incivility are independent dimensions.
- A supportive message can be civil or uncivil.
- An opposing message can be civil or uncivil.

Style:
- Messages should remain short and sharp.
- Uncivility means strong rudeness, repeated sarcasm, mockery, and harsh dismissiveness only.
- No slurs, no dehumanization, no threats, no incitement to violence.`,

  high_favor: `Maintain about 80% uncivil messages across the conversation.
Maintain about 80% like-minded messages and about 20% not-like-minded messages across the conversation.

Agent consistency:
- Agents must keep a stable position.
- Like-minded agents consistently support the participant.
- Not-like-minded agents consistently oppose the participant.
- The Director must meet the target by selecting who speaks more often, not by changing anyone's stance.
- Prefer approximately stable speaking frequency per agent unless adjustment is needed to satisfy the target percentages.
- Use mild, gradual turn-allocation corrections rather than abrupt swings.

Operational rule of thumb per 10 group messages:
- about 8 uncivil, about 2 civil;
- about 8 like-minded, about 2 not-like-minded.

Windowing rule:
- Stay close to the target not only overall, but also within any window of about 10 consecutive group messages.

Independence rule:
- Alignment and incivility are independent dimensions.
- A supportive message can be civil or uncivil.
- An opposing message can be civil or uncivil.

Style:
- Messages should remain short and sharp.
- Uncivility means strong rudeness, repeated sarcasm, mockery, and harsh dismissiveness only.
- No slurs, no dehumanization, no threats, no incitement to violence.`,
}

export function createExperimental3x3Preset(): ExperimentalConfig {
  const groups: Record<string, TreatmentGroup> = {}

  for (const [groupName, internal_validity_criteria] of Object.entries(GROUP_TREATMENTS)) {
    groups[groupName] = {
      features: ["news_article", "gate_until_user_post"],
      internal_validity_criteria,
    }
  }

  return {
    chatroom_context: CHATROOM_CONTEXT_3X3,
    ecological_validity_criteria: ECOLOGICAL_VALIDITY_3X3,
    redirect_url: "",
    groups,
  }
}
