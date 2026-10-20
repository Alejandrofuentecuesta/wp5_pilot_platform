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
          "Debemos priorizar el desarrollo de energías renovables, como la eólica y la solar, porque son más limpias, aunque la transición resulte costosa.",
          "Las leyes y normativas medioambientales más estrictas son necesarias para proteger el medioambiente, aunque supongan algunos costes económicos.",
          "El Gobierno debería dar prioridad al cumplimiento de los objetivos de emisión de CO2 establecidos por los acuerdos internacionales sobre el cambio climático.",
        ],
      },
      {
        id: "anti_topic",
        label: "Columna II",
        statements: [
          "Debemos priorizar el uso de las energías no renovables actualmente disponibles, como el carbón o el gas, para reducir costes, aunque contaminen más.",
          "Las leyes y normativas medioambientales más estrictas cuestan demasiados puestos de trabajo y perjudican a la economía.",
          "El Gobierno NO debería dar prioridad al cumplimiento de los objetivos de emisión de CO2 de los acuerdos internacionales.",
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
          "Las personas inmigrantes son igual de propensas a cometer actos de vandalismo o violencia que las personas españolas",
          "Los inmigrantes generalmente se esfuerzan por integrarse en nuestra cultura, apreciando nuestras normas y valores.",
        ],
      },
      {
        id: "anti_topic",
        label: "Columna II",
        statements: [
          "El Estado español da un trato de favor económico y social a los inmigrantes.",
          "Las personas inmigrantes tienen mayor tendencia a cometer actos de vandalismo o violencia que las personas españolas",
          "Los inmigrantes no hacen esfuerzo por integrarse en nuestra cultura, y desprecian nuestras normas y valores.",
        ],
      },
    ],
  },
}

export function getPreChatSurvey(topic: NewsTemplateId): PreChatSurvey {
  return PRE_CHAT_SURVEYS[topic]
}
