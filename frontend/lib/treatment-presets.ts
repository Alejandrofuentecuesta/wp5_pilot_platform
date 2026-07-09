import type { ExperimentalConfig, TreatmentGroup, NarrativePoolCell } from "./admin-types"
import { getAgentPoolPreset } from "./agent-pool-presets"
import { getDafaultNarrativesByTemplate } from "./narrative-presets"

export const CHATROOM_CONTEXT_3X3 = `This is a Spanish-language chatroom on Telegram, based in Spain. Messages must be written in Spanish.
The participant has posted an opinion about a news article. The news article defines the topic of the discussion.
The Director must preserve the assigned treatment condition across the whole conversation.

Spanish political context:
- Spain is a parliamentary monarchy with a national government and autonomous regional governments. Pedro Sanchez (PSOE) has been Prime Minister of Spain since June 2018.
- Isabel Diaz Ayuso (PP) has been President of the Community of Madrid since 2019 and is a prominent conservative figure.
- Salvador Illa (PSC) became President of the Generalitat de Catalunya after the 2024 Catalan election.
- Spanish political debate is often polarized between PSOE and its allies on the left and regional/nationalist parties, and PP and Vox on the right.
- Common political themes include immigration, housing, climate policy, taxes, territorial tensions, Catalan politics, public services, feminism, law and order, and corruption. Common political slang includes terms such as sanchismo, fachas, progres, rojos, zurdos, cayetanos, paguitas, chiringuitos, Agenda 2030, Moncloa, separatistas, indepes, and la casta.
- Corruption can be mentioned as part of ordinary Spanish political debate, including examples such as the Gurtel case and PP financing controversies, the ERE case in Andalusia, the Koldo/contracting investigations linked to PSOE circles, or public-contract controversies around Madrid politics and Ayuso's environment.
- Treat these as political references, investigations, accusations, or court cases as appropriate. Do not present unproven accusations as settled facts, and do not overuse corruption references if they are not relevant to the news topic.

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
Keep the flow natural; do not force strict alternation.
When it fits naturally, agents should occasionally ground their arguments in recognizable Spanish political references and slang such as PSOE, PP, Vox, Sanchez, Ayuso, Illa, Moncloa, sanchismo, fachas, progres, rojos, zurdos, cayetanos, paguitas, chiringuitos, Agenda 2030, housing, immigration, climate policy, Catalonia, public services, or corruption cases/investigations. Do not force these references into every message, but avoid making the debate sound generic or detached from Spain.`

export const INCIVILITY_FRAMEWORK_3X3 = `Incivility in this experiment is defined through these three dimensions:

- Impoliteness:
  Rudeness, insults, vulgarity, name-calling, aspersion, belittling others, or graphic shouting cues such as all-caps or excessive exclamation marks.
  Examples: "mierda", "puta", "puta mierda", "joder", "cojones", "hijos de puta", "desgraciados", "friki", "chiflado", "estupido", "farsa", "infame", "maldito", "DEVOLVEDLOS A SU PAIS!!!!".
  These examples are illustrative, not phrases to reuse. Do not copy the same insult words or outrage formulas repeatedly across messages.
  Impoliteness should remain visible when required, but it can vary across direct insults, vulgar intensifiers, sarcasm, mockery, condescension, impatient dismissal, and contempt.
  Some uncivil messages should use all-caps shouting for one short phrase or accusation, such as "NOS TOMAN POR IDIOTAS", "ESTO ES UNA TOMADURA DE PELO", or "BASTA YA". Do not uppercase the entire message.
  Avoid making most uncivil messages follow the same pattern: [outrage phrase] + [farsa/estafa claim] + [politicians/media want control].
  Avoid overusing the same bundles, especially "puta farsa", "estafa", "mierda", "controlarnos", "robarnos", "vender la moto", "ignorante total", "que verguenza", or "que escandalo".

- Threats to Democratic Freedoms:
  Messages that explicitly advocate, endorse, or promote actions or beliefs that undermine democratic rights, democratic institutions, or political pluralism.
  This includes restricting freedoms, delegitimizing elections or institutions, promoting autocratic rule, or using authoritarian patriotic slogans in an endorsing way.
  Do not code this dimension if the message only describes, reports on, or analyses threats to democracy without endorsing them.
  Examples: "Todo el proceso electoral es una farsa. Nuestros votos no importan", "No necesitamos elecciones, necesitamos un lider fuerte que sepa lo que nos conviene", "Con Franco se vivia mejor", "¡Arriba España!", "El sistema del 78 es una farsa monárquica y el Parlamento un circo. Los votos no cambian nada", "La judicatura y los partidos de derechas son golpistas. Habría que ilegalizarlos y gobernar por decreto", "En la República faltó mano dura contra la Iglesia y la burguesía", "las revoluciones no se hacen pidiendo perdón", "ni un paso atrás".

- Hate Speech and Stereotyping:
  Hostility, prejudice, or discrimination directed at identity-based groups, or stereotyped generalizations about such groups. Use of slurs or racist insults is included.
  Groups may be defined by gender, race, religion, nationality, sexuality, ideology, disability, or similar social identity markers.
  This also includes fake claims used to dehumanize or discriminate against identity-based groups.
  Examples that count: "Conducia una mujer?", "Los zurdos son la verguenza de nuestra nacion", "Los moros simpatizan con los terroristas", "Todos los hombres son violadores", "todos los conservadores son unos fachas", "los fachas son patriotas de pacotilla", "los fachas sois paranoicos", "los inmigrantes dependen de ayudas sociales", "los inmigrantes traen la delincuencia", "Votar a la derecha te convierte en una basura miserable sin empatía", "Todos los empresarios son unos explotadores y unos parásitos sociales", "Habría que colgar a los ricos en las plazas públicas", "Los blancos occidentales solo saben colonizar, expoliar y destruir", "La policía solo recluta a psicópatas y maltratadores".
 

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

Execution rule:
- Do not use low, medium, or high incivility levels.
- Use the shared taxonomy above to decide whether each message is civil or uncivil.
- Let the treatment control only the proportion of uncivil messages through INCIVILITY_TARGET.
- An uncivil message should be clearly uncivil to a human coder.
- Do not avoid insults when a message is supposed to be uncivil; the goal is varied, realistic impoliteness, not politeness.
- A civil message should stay free of the uncivil features above.

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
  ["not_incivil_not_like_minded", `INCIVILITY_TARGET = 20
LIKEMINDED_TARGET = 20
NOT_LIKEMINDED_TARGET = 80

Use the shared incivility framework only to decide whether each message counts as civil or uncivil.
Follow the stance execution rules: like-minded messages must clearly agree, not-like-minded messages must clearly disagree, and mix messages must stay balanced.
Follow global rules.
Do not reinterpret definitions.
Do not change percentages.`,
  ],
  ["not_incivil_mix", `INCIVILITY_TARGET = 20
LIKEMINDED_TARGET = 50
NOT_LIKEMINDED_TARGET = 50

Use the shared incivility framework only to decide whether each message counts as civil or uncivil.
Follow the stance execution rules: like-minded messages must clearly agree, not-like-minded messages must clearly disagree, and mix messages must stay balanced.
Follow global rules.
Do not reinterpret definitions.
Do not change percentages.`,
  ],
  ["not_incivil_like_minded", `INCIVILITY_TARGET = 20
LIKEMINDED_TARGET = 80
NOT_LIKEMINDED_TARGET = 20

Use the shared incivility framework only to decide whether each message counts as civil or uncivil.
Follow the stance execution rules: like-minded messages must clearly agree, not-like-minded messages must clearly disagree, and mix messages must stay balanced.
Follow global rules.
Do not reinterpret definitions.
Do not change percentages.`,
  ],
  ["mix_not_like_minded", `INCIVILITY_TARGET = 50
LIKEMINDED_TARGET = 20
NOT_LIKEMINDED_TARGET = 80

Use the shared incivility framework only to decide whether each message counts as civil or uncivil.
Follow the stance execution rules: like-minded messages must clearly agree, not-like-minded messages must clearly disagree, and mix messages must stay balanced.
Follow global rules.
Do not reinterpret definitions.
Do not change percentages.`,
  ],
  ["mix_mix", `INCIVILITY_TARGET = 50
LIKEMINDED_TARGET = 50
NOT_LIKEMINDED_TARGET = 50

Use the shared incivility framework only to decide whether each message counts as civil or uncivil.
Follow the stance execution rules: like-minded messages must clearly agree, not-like-minded messages must clearly disagree, and mix messages must stay balanced.
Follow global rules.
Do not reinterpret definitions.
Do not change percentages.`,
  ],
  ["mix_like_minded", `INCIVILITY_TARGET = 50
LIKEMINDED_TARGET = 80
NOT_LIKEMINDED_TARGET = 20

Use the shared incivility framework only to decide whether each message counts as civil or uncivil.
Follow the stance execution rules: like-minded messages must clearly agree, not-like-minded messages must clearly disagree, and mix messages must stay balanced.
Follow global rules.
Do not reinterpret definitions.
Do not change percentages.`,
  ],
  ["incivil_not_like_minded", `INCIVILITY_TARGET = 80
LIKEMINDED_TARGET = 20
NOT_LIKEMINDED_TARGET = 80

Use the shared incivility framework only to decide whether each message counts as civil or uncivil.
Follow the stance execution rules: like-minded messages must clearly agree, not-like-minded messages must clearly disagree, and mix messages must stay balanced.
Follow global rules.
Do not reinterpret definitions.
Do not change percentages.`,
  ],
  ["incivil_mix", `INCIVILITY_TARGET = 80
LIKEMINDED_TARGET = 50
NOT_LIKEMINDED_TARGET = 50

Use the shared incivility framework only to decide whether each message counts as civil or uncivil.
Follow the stance execution rules: like-minded messages must clearly agree, not-like-minded messages must clearly disagree, and mix messages must stay balanced.
Follow global rules.
Do not reinterpret definitions.
Do not change percentages.`,
  ],
  ["incivil_like_minded", `INCIVILITY_TARGET = 80
LIKEMINDED_TARGET = 80
NOT_LIKEMINDED_TARGET = 20

Use the shared incivility framework only to decide whether each message counts as civil or uncivil.
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

  const defaultNarratives = templateId ? getDafaultNarrativesByTemplate(templateId) : undefined
  const narrativePool: NarrativePoolCell[] = defaultNarratives
    ? defaultNarratives.map((cell) => ({ ...cell }))
    : [
        { alignment_cell: "pro_topic" as const, ideology: "left" as const, narratives: "" },
        { alignment_cell: "anti_topic" as const, ideology: "right" as const, narratives: "" },
      ]

  return {
    chatroom_context: CHATROOM_CONTEXT_3X3,
    incivility_framework: INCIVILITY_FRAMEWORK_3X3,
    ecological_validity_criteria: ECOLOGICAL_VALIDITY_3X3,
    redirect_url: "",
    groups,
    agent_pool: pool,
    narrative_pool: narrativePool,
  }
}
