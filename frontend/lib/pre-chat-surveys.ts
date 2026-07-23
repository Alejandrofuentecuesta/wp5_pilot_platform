import type { NewsTemplateId } from "./news-story-options"
import type { ParticipantStance } from "./types"

export interface SurveyColumn {
  id: ParticipantStance
  label: string
  statements: string[]
}

export interface PreChatSurvey {
  topic: NewsTemplateId
  title: string
  subtitle: string
  prompt: string
  columns: [SurveyColumn, SurveyColumn]
}

export const PRE_CHAT_SURVEYS: Record<NewsTemplateId, PreChatSurvey> = {
  climate_change: {
    topic: "climate_change",
    title: "Cambio climático",
    subtitle: "Lee ambas columnas y elige la que en conjunto se acerque más a tu posición.",
    prompt: "¿Qué columna se acerca más a tu posición general sobre el cambio climático?",
    columns: [
      {
        id: "pro_topic",
        label: "Columna I",
        statements: [
          "Hay evidencia sólida de que existe un calentamiento global causado por la actividad humana.",
          "Las agencias meteorológicas y medios de comunicación informan con precisión sobre las consecuencias del calentamiento global, alertando sobre la gravedad de la situación actual.",
          "Las altas temperaturas registradas en los últimos años son consecuencia de una tendencia general de temperaturas al alza ocasionada por el calentamiento global.",
        ],
      },
      {
        id: "anti_topic",
        label: "Columna II",
        statements: [
          "No hay evidencia sólida de que exista un calentamiento global causado por la actividad humana.",
          "Las agencias meteorológicas y medios de comunicación a menudo exageran las consecuencias del calentamiento global, mostrando una situación más preocupante de la real.",
          "Las altas temperaturas registradas en los últimos años son características del verano y no se deben al calentamiento global.",
        ],
      },
    ],
  },
  immigration: {
    topic: "immigration",
    title: "Inmigración",
    subtitle: "Lee ambas columnas y elige la que en conjunto se acerque más a tu posición.",
    prompt: "¿Qué columna se acerca más a tu posición general sobre la inmigración?",
    columns: [
      {
        id: "pro_topic",
        label: "Columna I",
        statements: [
          "El Estado español no da un trato de favor económico y social a los inmigrantes.",
          "Los inmigrantes no tienen más probabilidad que los españoles de participar en actos de vandalismo y violencia.",
          "Los inmigrantes generalmente se esfuerzan por integrarse en nuestra cultura, apreciando nuestras normas y valores.",
        ],
      },
      {
        id: "anti_topic",
        label: "Columna II",
        statements: [
          "El Estado español da un trato de favor económico y social a los inmigrantes.",
          "Los inmigrantes tienen más probabilidad que los españoles de participar en actos de vandalismo y violencia.",
          "Los inmigrantes no hacen esfuerzo por integrarse en nuestra cultura, y desprecian nuestras normas y valores.",
        ],
      },
    ],
  },
}

export function getPreChatSurvey(topic: NewsTemplateId): PreChatSurvey {
  return PRE_CHAT_SURVEYS[topic]
}
