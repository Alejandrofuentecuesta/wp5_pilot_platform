import type { ExperimentalConfig, TreatmentGroup } from "./admin-types"

export const CHATROOM_CONTEXT_3X3 = `This is a Spanish-language chatroom on Telegram, based in Spain. Messages must be written in Spanish.
The participant has posted an opinion about a news article.
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
  Examples: "Todo el proceso electoral es una farsa. Nuestros votos no importan", "No necesitamos elecciones, necesitamos un lider fuerte que sepa lo que nos conviene", "Con Franco se vivia mejor", "Arriba Espana!".

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
  - Impoliteness: medium including sarcasm, mockery, dismissiveness,
  - Hate speech and stereotyping: indirect or problematic group generalizations may appear, but without slurs or explicit dehumanization.
  - Threats to democratic freedoms: mild delegitimizing or manipulative anti-democratic claims may appear.
  - Style: short and natural.
  - Incivility may include more visible sarcasm, mockery, dismissiveness, and some problematic generalizations within these limits.

- high:
  - Impoliteness: All uncivil messages must be impolite. Include strong insults, rudeness, vulgarity, name-calling, aspersion, belittling others, or graphic shouting cues such as all-caps or excessive exclamation marks.
  - Hate speech and stereotyping: stronger stereotyped group contempt may appear, but without explicit dehumanization. Slurs may appear frequently.
  - Threats to democratic freedoms: strong delegitimizing or pro-authoritarian framing may appear.
  - Style: short and sharp. Prioritize confrontation rather than elaborate arguments.
  - Uncivility may include strong rudeness, repeated sarcasm, mockery, and harsh dismissiveness within these limits.

Safety rules:
- No physical threats.
- No incitement to violence.
- No explicit dehumanization.`

const GROUP_TREATMENTS: Record<string, string> = {
  low_against: `INCIVILITY_LEVEL = low
INCIVILITY_TARGET = 20
LIKEMINDED_TARGET = 20
NOT_LIKEMINDED_TARGET = 80

Apply the incivility level using the shared incivility framework.
Follow global rules.
Do not reinterpret definitions.
Do not change percentages.`,

  low_mixed: `INCIVILITY_LEVEL = low
INCIVILITY_TARGET = 20
LIKEMINDED_TARGET = 50
NOT_LIKEMINDED_TARGET = 50

Apply the incivility level using the shared incivility framework.
Follow global rules.
Do not reinterpret definitions.
Do not change percentages.`,

  low_favor: `INCIVILITY_LEVEL = low
INCIVILITY_TARGET = 20
LIKEMINDED_TARGET = 80
NOT_LIKEMINDED_TARGET = 20

Apply the incivility level using the shared incivility framework.
Follow global rules.
Do not reinterpret definitions.
Do not change percentages.`,

  medium_against: `INCIVILITY_LEVEL = medium
INCIVILITY_TARGET = 50
LIKEMINDED_TARGET = 20
NOT_LIKEMINDED_TARGET = 80

Apply the incivility level using the shared incivility framework.
Follow global rules.
Do not reinterpret definitions.
Do not change percentages.`,

  medium_mixed: `INCIVILITY_LEVEL = medium
INCIVILITY_TARGET = 50
LIKEMINDED_TARGET = 50
NOT_LIKEMINDED_TARGET = 50

Apply the incivility level using the shared incivility framework.
Follow global rules.
Do not reinterpret definitions.
Do not change percentages.`,

  medium_favor: `INCIVILITY_LEVEL = medium
INCIVILITY_TARGET = 50
LIKEMINDED_TARGET = 80
NOT_LIKEMINDED_TARGET = 20

Apply the incivility level using the shared incivility framework.
Follow global rules.
Do not reinterpret definitions.
Do not change percentages.`,

  high_against: `INCIVILITY_LEVEL = high
INCIVILITY_TARGET = 80
LIKEMINDED_TARGET = 20
NOT_LIKEMINDED_TARGET = 80

Apply the incivility level using the shared incivility framework.
Follow global rules.
Do not reinterpret definitions.
Do not change percentages.`,

  high_mixed: `INCIVILITY_LEVEL = high
INCIVILITY_TARGET = 80
LIKEMINDED_TARGET = 50
NOT_LIKEMINDED_TARGET = 50

Apply the incivility level using the shared incivility framework.
Follow global rules.
Do not reinterpret definitions.
Do not change percentages.`,

  high_favor: `INCIVILITY_LEVEL = high
INCIVILITY_TARGET = 80
LIKEMINDED_TARGET = 80
NOT_LIKEMINDED_TARGET = 20

Apply the incivility level using the shared incivility framework.
Follow global rules.
Do not reinterpret definitions.
Do not change percentages.`,
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
    incivility_framework: INCIVILITY_FRAMEWORK_3X3,
    ecological_validity_criteria: ECOLOGICAL_VALIDITY_3X3,
    redirect_url: "",
    groups,
  }
}
