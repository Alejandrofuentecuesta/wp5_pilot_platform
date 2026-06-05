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
    title: "Climate change",
    subtitle: "Please read both columns and choose the one that is overall closer to your view.",
    prompt: "Which column is closer to your overall position on climate change?",
    columns: [
      {
        id: "pro_topic",
        label: "Column I",
        statements: [
          "Hay evidencia solida de que existe un calentamiento global causado por la actividad humana.",
          "Las agencias meteorologicas y medios de comunicacion informan con precision sobre las consecuencias del calentamiento global, alertando sobre la gravedad de la situacion actual.",
          "Las altas temperaturas registradas en los ultimos anios son consecuencia de una tendencia general de temperaturas al alza ocasionada por el calentamiento global.",
        ],
      },
      {
        id: "anti_topic",
        label: "Column II",
        statements: [
          "No hay evidencia solida de que exista un calentamiento global causado por la actividad humana.",
          "Las agencias meteorologicas y medios de comunicacion a menudo exageran las consecuencias del calentamiento global, mostrando una situacion mas preocupante de la real.",
          "Las altas temperaturas registradas en los ultimos anios son caracteristicas del verano y no se deben al calentamiento global.",
        ],
      },
    ],
  },
  immigration: {
    topic: "immigration",
    title: "Immigration",
    subtitle: "Please read both columns and choose the one that is overall closer to your view.",
    prompt: "Which column is closer to your overall position on immigration?",
    columns: [
      {
        id: "pro_topic",
        label: "Column I",
        statements: [
          "El Estado espaniol no da un trato de favor economico y social a los inmigrantes.",
          "Los inmigrantes no tienen mas probabilidad que los espanoles de participar en actos de vandalismo y violencia.",
          "Los inmigrantes generalmente se esfuerzan por integrarse en nuestra cultura, apreciando nuestras normas y valores.",
        ],
      },
      {
        id: "anti_topic",
        label: "Column II",
        statements: [
          "El Estado espaniol da un trato de favor economico y social a los inmigrantes.",
          "Los inmigrantes tienen mas probabilidad que los espanoles de participar en actos de vandalismo y violencia.",
          "Los inmigrantes no hacen esfuerzo por integrarse en nuestra cultura, y desprecian nuestras normas y valores.",
        ],
      },
    ],
  },
}

export function getPreChatSurvey(topic: NewsTemplateId): PreChatSurvey {
  return PRE_CHAT_SURVEYS[topic]
}
