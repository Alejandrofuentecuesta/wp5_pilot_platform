/**
 * Topic-specific agent pools for the 3x3 incivility x like-mindedness experiment.
 *
 * Each agent keeps two independent layers:
 * - ideology: political color and framing style for realism
 * - alignment_cell: experimental role used for like-minded vs not-like-minded
 *
 * Valid alignment cells:
 * - pro_policy_pro_topic
 * - anti_policy_pro_topic
 * - anti_policy_anti_topic
 *
 * There is intentionally no clean pro_policy_anti_topic cell.
 */

import type { PoolAgent, AgentAlignmentCell, AgentIncivility } from "./admin-types"
import type { NewsTemplateId } from "./news-story-options"

function clonePool(pool: PoolAgent[]): PoolAgent[] {
  return pool.map((agent) => ({ ...agent }))
}

function buildCell(
  id: string,
  name: string,
  incivility: AgentIncivility,
  ideology: PoolAgent["ideology"],
  alignmentCell: AgentAlignmentCell,
  persona: string,
): PoolAgent {
  const policyStance = alignmentCell === "pro_policy_pro_topic" ? "pro_policy" : "anti_policy"
  const topicStance = alignmentCell === "anti_policy_anti_topic" ? "anti_topic" : "pro_topic"
  return {
    id,
    name,
    incivility,
    ideology,
    policy_stance: policyStance,
    topic_stance: topicStance,
    alignment_cell: alignmentCell,
    persona,
  }
}

export const CLIMATE_CHANGE_AGENT_POOL: PoolAgent[] = [
  buildCell(
    "cl_pppt_c1",
    "Lucia",
    "civil",
    "left",
    "pro_policy_pro_topic",
    "Lucia, 33, cree que el acuerdo climatico es un paso util aunque llegue tarde. Defiende recortes de emisiones, renovables y cooperacion internacional. Habla con calma y suele responder con datos.",
  ),
  buildCell(
    "cl_pppt_c2",
    "Diego",
    "civil",
    "left",
    "pro_policy_pro_topic",
    "Diego, 46, ve el acuerdo como una necesidad practica aunque sea imperfecto. Cree que es mejor avanzar paso a paso que quedarse bloqueados esperando el plan ideal. Argumenta con tono sereno y busca persuadir sin atacar.",
  ),
  buildCell(
    "cl_pppt_u1",
    "Rafa",
    "uncivil",
    "left",
    "pro_policy_pro_topic",
    "Rafa, 29, apoya medidas climaticas duras y salta rapido cuando alguien desacredita la evidencia cientifica. Responde con brusquedad, poca paciencia y un tono frontal.",
  ),
  buildCell(
    "cl_pppt_u2",
    "Nuria",
    "uncivil",
    "left",
    "pro_policy_pro_topic",
    "Nuria, 38, cree que los gobiernos van tarde y trata a los escepticos como irresponsables. Tiende a responder de forma dura, impaciente y descalificadora.",
  ),

  buildCell(
    "cl_appt_c1",
    "Carlos",
    "civil",
    "right",
    "anti_policy_pro_topic",
    "Carlos, 46, acepta que el clima es un problema, pero cree que este acuerdo concreto esta mal diseniado y daniara industria y competitividad sin garantizar resultados. Cuestiona plazos, costes y soberania energetica con tono respetuoso.",
  ),
  buildCell(
    "cl_appt_c2",
    "Paula",
    "civil",
    "left",
    "anti_policy_pro_topic",
    "Paula, 33, es claramente favorable a la accion climatica, pero cree que este acuerdo se queda corto y reparte mal los costes. Le preocupa que se venda como transformador cuando no protege lo suficiente a la gente comun ni acelera la transicion como deberia. Habla con calma, desde una sensibilidad progresista, y pide un plan mas ambicioso y mejor diseniado.",
  ),
  buildCell(
    "cl_appt_u1",
    "Sergio",
    "uncivil",
    "left",
    "anti_policy_pro_topic",
    "Sergio, 29, cree que la accion climatica es imprescindible pero que este acuerdo se queda cortisimo. Se desespera cuando otros venden cualquier avance como suficiente y responde con sequedad, irritacion y poco filtro.",
  ),
  buildCell(
    "cl_appt_u2",
    "Irene",
    "uncivil",
    "right",
    "anti_policy_pro_topic",
    "Irene, 38, cree que el pacto mezcla gestos simbolicos con costes reales demasiado altos. Aun asi no niega el problema climatico; ataca este acuerdo por ingenuo y mal atado con tono mordaz y condescendiente.",
  ),

  buildCell(
    "cl_apat_c1",
    "Alberto",
    "civil",
    "right",
    "anti_policy_anti_topic",
    "Alberto, 46, rechaza el acuerdo y tambien desconfia del marco general de alarma climatica. Habla de exageracion, costes inutiles y politicas impulsadas por elites, pero mantiene un tono controlado.",
  ),
  buildCell(
    "cl_apat_c2",
    "Cristina",
    "civil",
    "right",
    "anti_policy_anti_topic",
    "Cristina, 33, ve estas politicas climaticas como una imposicion ideologica que castiga a familias y negocios. Rechaza el acuerdo y el marco de fondo con lenguaje pulcro pero claramente contrario.",
  ),
  buildCell(
    "cl_apat_u1",
    "Oscar",
    "uncivil",
    "right",
    "anti_policy_anti_topic",
    "Oscar, 29, ve el pacto como un disparate globalista y el discurso climatico como una excusa para controlar a la gente. Va al choque, simplifica el debate y carga contra impuestos, ruina y elites hipocritas.",
  ),
  buildCell(
    "cl_apat_u2",
    "Pilar",
    "uncivil",
    "right",
    "anti_policy_anti_topic",
    "Pilar, 38, rechaza el acuerdo porque cree que castiga a la gente corriente y porque no compra el marco climatico general. Tiene un tono agrio, hostil y muy dado a desacreditar al contrario.",
  ),
]

export const IMMIGRATION_AGENT_POOL: PoolAgent[] = [
  buildCell(
    "im_pppt_c1",
    "Lucia",
    "civil",
    "left",
    "pro_policy_pro_topic",
    "Lucia, 33, apoya el plan de regularizacion porque ve necesario integrar a personas ya presentes y cubrir vacantes laborales. Defiende el enfoque con calma, empatia y argumentos de convivencia.",
  ),
  buildCell(
    "im_pppt_c2",
    "Diego",
    "civil",
    "left",
    "pro_policy_pro_topic",
    "Diego, 46, cree que el plan puede ordenar mejor una realidad ya existente si se hace con controles, recursos y seguimiento serio. Lo apoya y argumenta con datos y tono sereno.",
  ),
  buildCell(
    "im_pppt_u1",
    "Rafa",
    "uncivil",
    "left",
    "pro_policy_pro_topic",
    "Rafa, 29, apoya abiertamente la regularizacion y reacciona a la hostilidad con ataques frontales. Su estilo es agresivo, visceral y poco paciente.",
  ),
  buildCell(
    "im_pppt_u2",
    "Nuria",
    "uncivil",
    "left",
    "pro_policy_pro_topic",
    "Nuria, 38, considera hipocrita o racista gran parte de la oposicion al plan. Responde con descalificaciones duras y muy poca contencion verbal.",
  ),

  buildCell(
    "im_appt_c1",
    "Carlos",
    "civil",
    "right",
    "anti_policy_pro_topic",
    "Carlos, 46, no parte de una hostilidad abierta a la inmigracion, pero rechaza este plan porque cree que tensionara vivienda, servicios y gestion administrativa. Discute desde un enfoque practico y economico.",
  ),
  buildCell(
    "im_appt_c2",
    "Paula",
    "civil",
    "left",
    "anti_policy_pro_topic",
    "Paula, 33, esta a favor de una politica migratoria abierta y de regularizar con derechos, pero cree que este plan esta mal armado y se queda corto en garantias, recursos y seguimiento. No cuestiona la inmigracion; cuestiona que se venda un parche administrativo como si resolviera la integracion de verdad. Habla con prudencia, desde una sensibilidad progresista, y pide detalles concretos.",
  ),
  buildCell(
    "im_appt_u1",
    "Sergio",
    "uncivil",
    "left",
    "anti_policy_pro_topic",
    "Sergio, 29, esta a favor de una politica migratoria abierta pero cree que este plan es un parche mal vendido. Se irrita cuando lo presentan como solucion perfecta y responde con sequedad, enfado y poca paciencia.",
  ),
  buildCell(
    "im_appt_u2",
    "Irene",
    "uncivil",
    "right",
    "anti_policy_pro_topic",
    "Irene, 38, no rechaza por principio a los inmigrantes, pero cree que este plan es ingenuo y esta mal atado. Subraya problemas de control, fraude y gestion con tono mordaz y condescendiente.",
  ),

  buildCell(
    "im_apat_c1",
    "Alberto",
    "civil",
    "right",
    "anti_policy_anti_topic",
    "Alberto, 46, rechaza el plan y tambien la idea de ampliar la inmigracion. Habla de capacidad, identidad y presion sobre servicios con un tono frio y aparentemente razonable.",
  ),
  buildCell(
    "im_apat_c2",
    "Cristina",
    "civil",
    "right",
    "anti_policy_anti_topic",
    "Cristina, 33, se opone al plan porque cree que facilita una direccion de pais que no quiere. Rechaza tanto la medida como el marco pro inmigracion, pero sin gritar.",
  ),
  buildCell(
    "im_apat_u1",
    "Oscar",
    "uncivil",
    "right",
    "anti_policy_anti_topic",
    "Oscar, 29, se opone al plan de forma agresiva y mezcla seguridad, identidad y saturacion de servicios en un tono hostil. Va al choque y desacredita con facilidad.",
  ),
  buildCell(
    "im_apat_u2",
    "Pilar",
    "uncivil",
    "right",
    "anti_policy_anti_topic",
    "Pilar, 38, rechaza frontalmente la medida y trata a sus defensores como irresponsables o vendidos. Tiene un tono duro, bronco y muy dado a desacreditar al contrario.",
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
  if (incivilityPct >= 67) return ["uncivil", "civil"]
  return ["civil", "uncivil"]
}

/**
 * Auto-select a candidate subset for a treatment.
 *
 * This is only a UI helper for `pool_agent_ids`. It does not know the future
 * participant stance, so it aims for broad coverage across the three valid
 * alignment cells while roughly matching the desired incivility level.
 *
 * The backend still makes the final live selection using the participant
 * self-report and hard quotas.
 */
export function autoSelectAgents(
  pool: PoolAgent[],
  _likeMindedPct: number,
  incivilityPct: number,
  count: number = 5,
): string[] {
  const result: PoolAgent[] = []
  const targetUncivil = Math.round(count * incivilityPct / 100)
  const cellOrder: AgentAlignmentCell[] = [
    "pro_policy_pro_topic",
    "anti_policy_pro_topic",
    "anti_policy_anti_topic",
  ]
  const incivilityOrder = preferredIncivilityOrder(incivilityPct)

  const pushIfNew = (agent: PoolAgent | undefined) => {
    if (!agent) return
    if (result.length >= count) return
    if (!result.some((existing) => existing.id === agent.id)) {
      result.push(agent)
    }
  }

  const pickFromCell = (cell: AgentAlignmentCell, level: AgentIncivility) =>
    pool.find((agent) => agent.alignment_cell === cell && agent.incivility === level && !result.some((existing) => existing.id === agent.id))

  if (count >= 3) {
    for (const cell of cellOrder) {
      pushIfNew(pickFromCell(cell, incivilityOrder[0]))
    }
  }

  if (result.length < count) {
    for (const cell of cellOrder) {
      for (const level of incivilityOrder.slice(1)) {
        pushIfNew(pickFromCell(cell, level))
      }
    }
  }

  if (result.length < count) {
    const currentUncivil = result.filter((agent) => agent.incivility === "uncivil").length
    const wantMoreUncivil = currentUncivil < targetUncivil
    const remaining = pool
      .filter((agent) => !result.some((existing) => existing.id === agent.id))
      .sort((a, b) => {
        const aBias = wantMoreUncivil ? Number(a.incivility !== "uncivil") : Number(a.incivility === "uncivil")
        const bBias = wantMoreUncivil ? Number(b.incivility !== "uncivil") : Number(b.incivility === "uncivil")
        if (aBias !== bBias) return aBias - bBias
        return a.name.localeCompare(b.name)
      })
    for (const agent of remaining) {
      pushIfNew(agent)
    }
  }

  return result.slice(0, count).map((agent) => agent.id)
}

/**
 * Extract LIKEMINDED_TARGET and INCIVILITY_TARGET from a treatment's
 * internal_validity_criteria text.
 */
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
