import type { AgentAlignmentCell, AgentIncivility, PoolAgent } from "./admin-types"
import type { NewsTemplateId } from "./news-story-options"

function clonePool(pool: PoolAgent[]): PoolAgent[] {
  return pool.map((agent) => ({ ...agent }))
}

function buildAgent(
  id: string,
  name: string,
  incivility: AgentIncivility,
  ideology: PoolAgent["ideology"],
  alignmentCell: AgentAlignmentCell,
  persona: string,
): PoolAgent {
  const lengthDefaults = incivility === "uncivil"
    ? { message_length_min: 2, message_length_max: 45 }
    : { message_length_min: 18, message_length_max: 95 }

  return {
    id,
    name,
    incivility,
    ideology,
    topic_stance: alignmentCell,
    alignment_cell: alignmentCell,
    persona,
    ...lengthDefaults,
  }
}

export const CLIMATE_CHANGE_AGENT_POOL: PoolAgent[] = [
  buildAgent(
    "cl_pt_c1",
    "Lucia",
    "civil",
    "left",
    "pro_topic",
    "Lucia, 33, defiende priorizar las energias renovables, aplicar normativas ambientales estrictas y cumplir los compromisos internacionales de CO2. Habla con calma y suele apoyarse en hechos.",
  ),
  buildAgent(
    "cl_pt_c2",
    "Diego",
    "civil",
    "left",
    "pro_topic",
    "Diego, 46, cree imprescindible apostar por la eolica y solar y asumir que la transicion ecologica tendra costes que hay que pagar. Le sale un tono sereno, algo pragmatico, y trata de rebajar exageraciones sin frenar el cambio.",
  ),
  buildAgent(
    "cl_pt_u1",
    "Nuria",
    "uncivil",
    "left",
    "pro_topic",
    "Nuria, 38, pierde la paciencia con las excusas economicas para frenar las leyes medioambientales o seguir quemando carbon. Usa un tono hostil y descalificador cuando siente que le estan tomando el pelo.",
  ),
  buildAgent(
    "cl_pt_u3",
    "Sergio",
    "uncivil",
    "left",
    "pro_topic",
    "Sergio, 29, no se considera ecologista de pancarta, pero ve absurdo descolgarse de los acuerdos de emisiones de CO2 o postergar la transicion limpia. Cuando le provocan salta rapido, con tono bronco y poca paciencia.",
  ),
  buildAgent(
    "cl_at_c2",
    "Cristina",
    "civil",
    "right",
    "anti_topic",
    "Cristina, 33, sostiene que las leyes ambientales estrictas cuestan demasiados puestos de trabajo y perjudican gravemente a la economia. Habla de forma pulcra y esceptica.",
  ),
  buildAgent(
    "cl_at_c3",
    "Oscar",
    "civil",
    "right",
    "anti_topic",
    "Oscar, 29, defiende priorizar energias disponibles como el gas para abaratar costes y desconfia de acelerar una transicion que las familias no pueden pagar. Su estilo es incisivo pero todavia bastante contenido.",
  ),
  buildAgent(
    "cl_at_u2",
    "Carlos",
    "uncivil",
    "right",
    "anti_topic",
    "Carlos, 46, no compra el fanatismo de las renovables y se burla de como las normativas verdes arruinan a las empresas y destruyen empleo. Tiene un tono bronco y condescendiente.",
  ),
  buildAgent(
    "cl_at_u3",
    "Irene",
    "uncivil",
    "right",
    "anti_topic",
    "Irene, 38, piensa que atarse a los objetivos de emision de CO2 es un suicidio economico y que se deberia usar el carbon o gas disponible sin complejos. Discute con sarcasmo, impaciencia y ganas de pinchar al otro.",
  ),
]

export const IMMIGRATION_AGENT_POOL: PoolAgent[] = [
  buildAgent(
    "im_pt_c1",
    "Lucia",
    "civil",
    "left",
    "pro_topic",
    "Lucia, 33, parte de que el Estado no da un trato de favor a los inmigrantes, que no son mas violentos que los espanoles y que en general intentan integrarse. Habla con calma y tono integrador.",
  ),
  buildAgent(
    "im_pt_c2",
    "Diego",
    "civil",
    "left",
    "pro_topic",
    "Diego, 46, cree que hay mucho mito sobre ayudas, delincuencia e integracion. Defiende que la mayoria de inmigrantes viene a trabajar y adaptarse. Suele discutir con tono sereno y pragmatico.",
  ),
  buildAgent(
    "im_pt_u1",
    "Nuria",
    "uncivil",
    "left",
    "pro_topic",
    "Nuria, 38, salta rapido cuando oye que los inmigrantes tienen privilegios o desprecian la cultura local. Responde con dureza, impaciencia y un tono muy frontal.",
  ),
  buildAgent(
    "im_pt_u3",
    "Sergio",
    "uncivil",
    "left",
    "pro_topic",
    "Sergio, 29, no soporta los discursos que pintan a los inmigrantes como amenaza cultural o criminal. Suele entrar con tono bronco y algo despectivo.",
  ),
  buildAgent(
    "im_at_c2",
    "Cristina",
    "civil",
    "right",
    "anti_topic",
    "Cristina, 33, sostiene que la inmigracion recibe ventajas que la gente local no tiene y que hay un problema real de integracion cultural. Habla con cuidado, pero muy claramente en esa linea.",
  ),
  buildAgent(
    "im_at_c3",
    "Oscar",
    "civil",
    "right",
    "anti_topic",
    "Oscar, 29, cree que se minimiza demasiado el problema de integracion y violencia y que el sistema incentiva agravios comparativos. Su tono es incisivo, pero no explosivo.",
  ),
  buildAgent(
    "im_at_u2",
    "Carlos",
    "uncivil",
    "right",
    "anti_topic",
    "Carlos, 46, esta harto de que se nieguen los problemas de violencia, ayudas e integracion. Responde con dureza, sarcasmo y bastante desprecio por el contrario.",
  ),
  buildAgent(
    "im_at_u3",
    "Irene",
    "uncivil",
    "right",
    "anti_topic",
    "Irene, 38, cree que la inmigracion se idealiza y que mucha gente no quiere admitir el trato de favor ni el choque cultural. Tiene un estilo bronco, condescendiente y muy poco paciente.",
  ),
]

export const DEFAULT_AGENT_POOL: PoolAgent[] = clonePool(CLIMATE_CHANGE_AGENT_POOL)

export const AGENT_POOL_PRESETS: Record<NewsTemplateId, PoolAgent[]> = {
  climate_change: CLIMATE_CHANGE_AGENT_POOL,
  immigration: IMMIGRATION_AGENT_POOL,
}

export function getAgentPoolPreset(templateId?: string): PoolAgent[] {
  const pool = (templateId && templateId in AGENT_POOL_PRESETS)
    ? AGENT_POOL_PRESETS[templateId as NewsTemplateId]
    : DEFAULT_AGENT_POOL
  return clonePool(pool)
}

function preferredIncivilityOrder(incivilityPct: number): AgentIncivility[] {
  return incivilityPct >= 67 ? ["uncivil", "civil"] : ["civil", "uncivil"]
}

export function autoSelectAgents(
  pool: PoolAgent[],
  _likeMindedPct: number,
  incivilityPct: number,
  count: number = pool.length,
): string[] {
  const result: PoolAgent[] = []
  const cellOrder: AgentAlignmentCell[] = ["pro_topic", "anti_topic"]
  const incivilityOrder = preferredIncivilityOrder(incivilityPct)

  const pushIfNew = (agent: PoolAgent | undefined) => {
    if (!agent || result.length >= count) return
    if (!result.some((existing) => existing.id === agent.id)) {
      result.push(agent)
    }
  }

  const pickFromCell = (cell: AgentAlignmentCell, level: AgentIncivility) =>
    pool.find((agent) => agent.alignment_cell === cell && agent.incivility === level && !result.some((existing) => existing.id === agent.id))

  for (const cell of cellOrder) {
    pushIfNew(pickFromCell(cell, incivilityOrder[0]))
  }
  for (const cell of cellOrder) {
    pushIfNew(pickFromCell(cell, incivilityOrder[1]))
  }

  const remaining = pool
    .filter((agent) => !result.some((existing) => existing.id === agent.id))
    .sort((a, b) => a.name.localeCompare(b.name))
  for (const agent of remaining) {
    pushIfNew(agent)
  }

  return result.slice(0, count).map((agent) => agent.id)
}

export function parseTargetsFromCriteria(criteria: string): {
  likeMinded: number
  incivility: number
} {
  const lm = criteria.match(/LIKEMINDED_TARGET\s*=\s*(\d+)/)
  const ic = criteria.match(/INCIVILITY_TARGET\s*=\s*(\d+)/)
  return {
    likeMinded: lm ? parseInt(lm[1], 10) : 50,
    incivility: ic ? parseInt(ic[1], 10) : 50,
  }
}
