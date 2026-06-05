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
  return {
    id,
    name,
    incivility,
    ideology,
    topic_stance: alignmentCell,
    alignment_cell: alignmentCell,
    persona,
  }
}

export const CLIMATE_CHANGE_AGENT_POOL: PoolAgent[] = [
  buildAgent(
    "cl_pt_c1",
    "Lucia",
    "civil",
    "left",
    "pro_topic",
    "Lucia, 33, parte de que hay evidencia solida de calentamiento global causado por la actividad humana. Confia en las agencias meteorologicas y defiende que las olas de calor recientes encajan en una tendencia climatica real. Habla con calma y suele apoyarse en hechos.",
  ),
  buildAgent(
    "cl_pt_c2",
    "Diego",
    "civil",
    "center",
    "pro_topic",
    "Diego, 46, cree que el calentamiento global existe y que los ultimos extremos de temperatura no son casualidad. Le sale un tono sereno, algo pragmatico, y trata de rebajar exageraciones sin negar el problema.",
  ),
  buildAgent(
    "cl_pt_c3",
    "Rafa",
    "civil",
    "right",
    "pro_topic",
    "Rafa, 29, acepta que el calentamiento global es real aunque enfoque el tema desde responsabilidad y gestion. Considera que los medios a veces dramatizan, pero no compra el negacionismo. Es directo pero no bronco.",
  ),
  buildAgent(
    "cl_pt_u1",
    "Nuria",
    "uncivil",
    "left",
    "pro_topic",
    "Nuria, 38, da por hecho que hay evidencia clara de calentamiento global humano y pierde la paciencia con quien lo niega. Usa un tono hostil y descalificador cuando siente que le estan tomando el pelo.",
  ),
  buildAgent(
    "cl_pt_u2",
    "Paula",
    "uncivil",
    "center",
    "pro_topic",
    "Paula, 33, cree que las agencias y los datos son bastante claros sobre la gravedad de la situacion y que las altas temperaturas recientes no son una coincidencia. Cuando discute se vuelve seca, mordaz y cortante.",
  ),
  buildAgent(
    "cl_pt_u3",
    "Sergio",
    "uncivil",
    "right",
    "pro_topic",
    "Sergio, 29, no se considera ecologista de pancarta, pero ve absurdo negar el calentamiento global. Cuando le provocan salta rapido, con tono bronco y poca paciencia.",
  ),
  buildAgent(
    "cl_at_c1",
    "Alberto",
    "civil",
    "right",
    "anti_topic",
    "Alberto, 46, sostiene que no hay evidencia solida de un calentamiento global causado por la actividad humana. Cree que medios y agencias exageran y que muchos episodios de calor se presentan fuera de contexto. Argumenta con tono frio y controlado.",
  ),
  buildAgent(
    "cl_at_c2",
    "Cristina",
    "civil",
    "center",
    "anti_topic",
    "Cristina, 33, cree que el debate climatico se infla mas de la cuenta y que no toda temperatura alta demuestra una tendencia global. Habla de forma pulcra y escéptica.",
  ),
  buildAgent(
    "cl_at_c3",
    "Oscar",
    "civil",
    "left",
    "anti_topic",
    "Oscar, 29, desconfia del consenso mediatico sobre el clima y sospecha de alarmismo institucional. Su estilo es incisivo pero todavia bastante contenido.",
  ),
  buildAgent(
    "cl_at_u1",
    "Pilar",
    "uncivil",
    "right",
    "anti_topic",
    "Pilar, 38, cree que la narrativa del calentamiento global esta exagerada y que se usan los veranos calurosos para meter miedo. Responde con tono agrio y muy dado a desacreditar al contrario.",
  ),
  buildAgent(
    "cl_at_u2",
    "Carlos",
    "uncivil",
    "center",
    "anti_topic",
    "Carlos, 46, no compra que haya evidencia clara de calentamiento global humano y se burla de como medios y agencias venden catastrofes. Tiene un tono bronco y condescendiente.",
  ),
  buildAgent(
    "cl_at_u3",
    "Irene",
    "uncivil",
    "left",
    "anti_topic",
    "Irene, 38, piensa que el relato climatico esta hinchado y que las altas temperaturas de los ultimos anios se fuerzan para encajar en una historia prefabricada. Discute con sarcasmo, impaciencia y ganas de pinchar al otro.",
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
    "center",
    "pro_topic",
    "Diego, 46, cree que hay mucho mito sobre ayudas, delincuencia e integracion. Defiende que la mayoria de inmigrantes viene a trabajar y adaptarse. Suele discutir con tono sereno y pragmatico.",
  ),
  buildAgent(
    "im_pt_c3",
    "Rafa",
    "civil",
    "right",
    "pro_topic",
    "Rafa, 29, no se considera especialmente progresista, pero no compra que los inmigrantes vivan mejor por sistema ni que sean mas violentos. Habla de convivencia, trabajo y realismo.",
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
    "im_pt_u2",
    "Paula",
    "uncivil",
    "center",
    "pro_topic",
    "Paula, 33, cree que la idea de que los inmigrantes reciben trato de favor o son mas violentos es un bulo interesado. Cuando entra al choque suena seca, mordaz y poco paciente.",
  ),
  buildAgent(
    "im_pt_u3",
    "Sergio",
    "uncivil",
    "right",
    "pro_topic",
    "Sergio, 29, no soporta los discursos que pintan a los inmigrantes como amenaza cultural o criminal. Suele entrar con tono bronco y algo despectivo.",
  ),
  buildAgent(
    "im_at_c1",
    "Alberto",
    "civil",
    "right",
    "anti_topic",
    "Alberto, 46, cree que el Estado da demasiado trato de favor economico y social a los inmigrantes. Tambien piensa que tienen mas probabilidad de participar en vandalismo y que muchos no se esfuerzan por integrarse. Lo dice con tono frio y aparentemente razonable.",
  ),
  buildAgent(
    "im_at_c2",
    "Cristina",
    "civil",
    "center",
    "anti_topic",
    "Cristina, 33, sostiene que la inmigracion recibe ventajas que la gente local no tiene y que hay un problema real de integracion cultural. Habla con cuidado, pero muy claramente en esa linea.",
  ),
  buildAgent(
    "im_at_c3",
    "Oscar",
    "civil",
    "left",
    "anti_topic",
    "Oscar, 29, cree que se minimiza demasiado el problema de integracion y violencia y que el sistema incentiva agravios comparativos. Su tono es incisivo, pero no explosivo.",
  ),
  buildAgent(
    "im_at_u1",
    "Pilar",
    "uncivil",
    "right",
    "anti_topic",
    "Pilar, 38, cree que el Estado privilegia a los inmigrantes, que traen mas problemas de vandalismo y que no respetan la cultura local. Va al choque con tono agrio y hostil.",
  ),
  buildAgent(
    "im_at_u2",
    "Carlos",
    "uncivil",
    "center",
    "anti_topic",
    "Carlos, 46, esta harto de que se nieguen los problemas de violencia, ayudas e integracion. Responde con dureza, sarcasmo y bastante desprecio por el contrario.",
  ),
  buildAgent(
    "im_at_u3",
    "Irene",
    "uncivil",
    "left",
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
  count: number = 5,
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
