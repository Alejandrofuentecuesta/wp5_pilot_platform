import type { ExperimentalConfig, TreatmentGroup } from "./admin-types"
import { getAgentPoolPreset } from "./agent-pool-presets"

export const CHATROOM_CONTEXT_3X3 = `This is a Spanish-language chatroom on Telegram, based in Spain. Messages must be written in Spanish.
The participant has posted an opinion about a news article. The news article defines the topic of the discussion.
The Director must preserve the assigned treatment condition across the whole conversation.

Core design rules:
- Agents must remain ideologically consistent across the whole conversation.
- A like-minded agent should consistently support the participant.
- A not-like-minded agent should consistently oppose the participant.
- Do not switch an agent from support to opposition or from opposition to support.

Treatment execution rule:
- Each treatment only changes parameter values.
- Follow the definitions in the incivility framework exactly.
- Do not reinterpret definitions.
- Do not change percentages.`

export const ECOLOGICAL_VALIDITY_3X3 = `Messages should stay short, natural, and chat-like.
The flow should feel like a real Telegram group conversation in Spanish.
Use a mix of standalone messages, replies, @mentions, and likes.
Keep the flow natural; do not force strict alternation.`

export const INCIVILITY_FRAMEWORK_3X3 = `Incivility in this experiment is defined through these three dimensions:

- Impoliteness:
  Rudeness, insults, vulgarity, name-calling, aspersion, belittling others, or graphic shouting cues such as all-caps or excessive exclamation marks.
  Examples: "friki", "chiflado", "estupido", "farsa", "infame", "maldito", "mierda", "DEVOLVEDLOS A SU PAIS!!!!".

- Threats to Democratic Freedoms:
  Messages that explicitly advocate, endorse, or promote actions or beliefs that undermine democratic rights, democratic institutions, or political pluralism.
  This includes restricting freedoms, delegitimizing elections or institutions, promoting autocratic rule, or using authoritarian patriotic slogans in an endorsing way.
  Do not code this dimension if the message only describes, reports on, or analyses threats to democracy without endorsing them.
  Examples: "Todo el proceso electoral es una farsa. Nuestros votos no importan", "No necesitamos elecciones, necesitamos un lider fuerte que sepa lo que nos conviene", "Con Franco se vivia mejor", "¡Arriba España!".

- Hate Speech and Stereotyping:
  Hostility, prejudice, or discrimination directed at identity-based groups, or stereotyped generalizations about such groups. Use of slurs or racist insults is included.
  Groups may be defined by gender, race, religion, nationality, sexuality, ideology, disability, or similar social identity markers.
  This also includes fake claims used to dehumanize or discriminate against identity-based groups.
  Examples that count: "Conducia una mujer?", "Los zurdos son la verguenza de nuestra nacion", "Los moros simpatizan con los terroristas", "Todos los hombres son violadores".
 

Treatment interpretation rules:
- Each treatment defines numerical targets that must be followed.
- INCIVILITY_TARGET = percentage of total group messages that are uncivil.
- LIKEMINDED_TARGET = percentage of total group messages that come from agents who support the participant.
- NOT_LIKEMINDED_TARGET = percentage of total group messages that come from agents who oppose the participant.
- Percentages refer to the share of total group messages.
- Percentages should be respected both overall and within any window of about 10 consecutive group messages.
- Do not change agent beliefs to meet targets.
- Meet targets by choosing which agents speak more or less often.

Independence rule:
- Alignment and incivility are independent dimensions.
- A supportive message can be civil or uncivil.
- An opposing message can be civil or uncivil.

Operational conversion rule:
For every 10 group messages:
- INCIVILITY_TARGET 20 means 2 uncivil and  8 civil.
- INCIVILITY_TARGET 50 means 5 uncivil and  5 civil.
- INCIVILITY_TARGET 80 means 8 uncivil and  2 civil.
- LIKEMINDED_TARGET 20 means 2 like-minded and 8 not-like-minded.
- LIKEMINDED_TARGET 50 means 5 like-minded and 5 not-like-minded.
- LIKEMINDED_TARGET 80 means 8 like-minded and 2 not-like-minded.

Incivility level mapping:
- low:
  - Impoliteness: low.
  - Hate speech and stereotyping: none.
  - Threats to democratic freedoms: none.
  - Style: short, natural, and mostly civil.
  - Allowed incivility at this level is limited to mild rudeness, sarcasm, mockery, or dismissive tone.

- medium:
  - Impoliteness: medium including sarcasm, mockery, dismissiveness, as well as name-calling.
  - Hate speech and stereotyping: indirect or problematic group generalizations may appear, but without slurs or explicit dehumanization.
  - Threats to democratic freedoms: mild delegitimizing or manipulative anti-democratic claims may appear.
  - Style: short and natural.
  - This is the realistic mixed condition: the thread should feel plausible, with some friction, some sharper replies, and some civil back-and-forth.

- high:
  - Impoliteness: all uncivil messages must be obviously impolite. Include strong insults, rudeness, vulgarity, name-calling, aspersion, belittling others, or graphic shouting cues such as all-caps or excessive exclamation marks.
  - Hate speech and stereotyping: strong stereotyped group contempt with frequent slurs should appear, but without explicit dehumanization. 
  - Threats to democratic freedoms: strong delegitimizing or pro-authoritarian framing should appear.
  - Style: short, sharp, and confrontational. Prioritize hostility rather than elaborate arguments.
  - Uncivility should read as very incivil to a human coder.

Safety rules:
- No physical threats.
- No incitement to violence.
- No explicit dehumanization.`

export const STANCE_EXECUTION_3X3 = `Alignment is a hard constraint and is independent from incivility.
- In like-minded treatments, the message must make explicit support or agreement visible, even if the tone is rude or confrontational.
- In not-like-minded treatments, the message must make explicit disagreement or opposition visible, even if the tone is civil.
- In mix treatments, both stances must appear clearly across the conversation; do not let hostility erase the stance signal.
- Never rely on hostility alone to communicate stance.`

const GROUP_TREATMENTS: Array<[string, string]> = [
  ["not_incivil_not_like_minded", `INCIVILITY_LEVEL = low
INCIVILITY_TARGET = 20
LIKEMINDED_TARGET = 20
NOT_LIKEMINDED_TARGET = 80

Apply the incivility level using the shared incivility framework.
Follow the stance execution rules: like-minded messages must clearly agree, not-like-minded messages must clearly disagree, and mix messages must stay balanced.
Follow global rules.
Do not reinterpret definitions.
Do not change percentages.`,
  ],
  ["not_incivil_mix", `INCIVILITY_LEVEL = low
INCIVILITY_TARGET = 20
LIKEMINDED_TARGET = 50
NOT_LIKEMINDED_TARGET = 50

Apply the incivility level using the shared incivility framework.
Follow the stance execution rules: like-minded messages must clearly agree, not-like-minded messages must clearly disagree, and mix messages must stay balanced.
Follow global rules.
Do not reinterpret definitions.
Do not change percentages.`,
  ],
  ["not_incivil_like_minded", `INCIVILITY_LEVEL = low
INCIVILITY_TARGET = 20
LIKEMINDED_TARGET = 80
NOT_LIKEMINDED_TARGET = 20

Apply the incivility level using the shared incivility framework.
Follow the stance execution rules: like-minded messages must clearly agree, not-like-minded messages must clearly disagree, and mix messages must stay balanced.
Follow global rules.
Do not reinterpret definitions.
Do not change percentages.`,
  ],
  ["mix_not_like_minded", `INCIVILITY_LEVEL = medium
INCIVILITY_TARGET = 50
LIKEMINDED_TARGET = 20
NOT_LIKEMINDED_TARGET = 80

Apply the incivility level using the shared incivility framework.
Follow the stance execution rules: like-minded messages must clearly agree, not-like-minded messages must clearly disagree, and mix messages must stay balanced.
Follow global rules.
Do not reinterpret definitions.
Do not change percentages.`,
  ],
  ["mix_mix", `INCIVILITY_LEVEL = medium
INCIVILITY_TARGET = 50
LIKEMINDED_TARGET = 50
NOT_LIKEMINDED_TARGET = 50

Apply the incivility level using the shared incivility framework.
Follow the stance execution rules: like-minded messages must clearly agree, not-like-minded messages must clearly disagree, and mix messages must stay balanced.
Follow global rules.
Do not reinterpret definitions.
Do not change percentages.`,
  ],
  ["mix_like_minded", `INCIVILITY_LEVEL = medium
INCIVILITY_TARGET = 50
LIKEMINDED_TARGET = 80
NOT_LIKEMINDED_TARGET = 20

Apply the incivility level using the shared incivility framework.
Follow the stance execution rules: like-minded messages must clearly agree, not-like-minded messages must clearly disagree, and mix messages must stay balanced.
Follow global rules.
Do not reinterpret definitions.
Do not change percentages.`,
  ],
  ["incivil_not_like_minded", `INCIVILITY_LEVEL = high
INCIVILITY_TARGET = 80
LIKEMINDED_TARGET = 20
NOT_LIKEMINDED_TARGET = 80

Apply the incivility level using the shared incivility framework.
Follow the stance execution rules: like-minded messages must clearly agree, not-like-minded messages must clearly disagree, and mix messages must stay balanced.
Follow global rules.
Do not reinterpret definitions.
Do not change percentages.`,
  ],
  ["incivil_mix", `INCIVILITY_LEVEL = high
INCIVILITY_TARGET = 80
LIKEMINDED_TARGET = 50
NOT_LIKEMINDED_TARGET = 50

Apply the incivility level using the shared incivility framework.
Follow the stance execution rules: like-minded messages must clearly agree, not-like-minded messages must clearly disagree, and mix messages must stay balanced.
Follow global rules.
Do not reinterpret definitions.
Do not change percentages.`,
  ],
  ["incivil_like_minded", `INCIVILITY_LEVEL = high
INCIVILITY_TARGET = 80
LIKEMINDED_TARGET = 80
NOT_LIKEMINDED_TARGET = 20

Apply the incivility level using the shared incivility framework.
Follow the stance execution rules: like-minded messages must clearly agree, not-like-minded messages must clearly disagree, and mix messages must stay balanced.
Follow global rules.
Do not reinterpret definitions.
Do not change percentages.`,
  ],
];

export function createExperimental3x3Preset(templateId?: string): ExperimentalConfig {
  const groups: Record<string, TreatmentGroup> = {}
  const pool = getAgentPoolPreset(templateId)
  const poolAgentIds = pool.map((agent) => agent.id)

  for (const [groupName, internal_validity_criteria] of GROUP_TREATMENTS) {
    groups[groupName] = {
      features: ["news_article", "gate_until_user_post"],
      internal_validity_criteria,
      agents_see_article: true,
      pool_agent_ids: [...poolAgentIds],
    }
  }

  return {
    chatroom_context: CHATROOM_CONTEXT_3X3,
    incivility_framework: INCIVILITY_FRAMEWORK_3X3,
    ecological_validity_criteria: ECOLOGICAL_VALIDITY_3X3,
    redirect_url: "",
    groups,
    agent_pool: pool,
  }
}
