import type { SeedArticle } from "./admin-types"

export type NewsTemplateId = "climate_change" | "immigration"

export interface NewsTemplateOption {
  id: NewsTemplateId
  label: string
  article: SeedArticle
}

export const NEWS_TEMPLATE_OPTIONS: NewsTemplateOption[] = [
  {
    id: "immigration",
    label: "Immigration",
    article: {
      type: "news_article",
      headline:
        "El Govern plantea un plan piloto para vincular permisos de residencia y empleo en sectores con vacantes y reabre el debate migratorio en Catalunya",
      source: "Reuters",
      agent_summary: "El Govern de Catalunya prevé presentar un plan piloto para regularizar temporalmente a unos 2.000 inmigrantes en situación irregular que acrediten arraigo y una oferta de empleo en sectores con escasez de mano de obra (agricultura, construcción, cuidados, hostelería). El plan incluiría formación lingüística obligatoria y coordinación entre administraciones. La medida divide a patronales, sindicatos, partidos y entidades sociales, y reabre el debate sobre integración, seguridad y presión sobre los servicios públicos.",
      body: `La propuesta, que incluiría formación lingüística obligatoria y un refuerzo de los controles de identidad en los primeros meses, divide a patronales, sindicatos, ayuntamientos y entidades sociales en un momento de creciente presión sobre la acogida y los servicios públicos.
La propuesta que el Govern prevé presentar la próxima semana para impulsar un plan piloto de inserción laboral de inmigrantes en sectores con falta de mano de obra ha reabierto en Catalunya un debate que trasciende la gestión administrativa y alcanza de lleno cuestiones económicas, de seguridad y de convivencia cultural. El borrador, todavía en fase de negociación con el Ejecutivo central, contempla facilitar itinerarios de regularización temporal para unas 2.000 personas en situación irregular que acrediten arraigo reciente y una oferta de empleo en actividades como la agricultura, la atención domiciliaria, la construcción o la hostelería.
Según fuentes conocedoras del documento, la iniciativa incluiría además cursos obligatorios de catalán o castellano, seguimiento social durante el primer año y un protocolo de coordinación entre Mossos d’Esquadra, ayuntamientos y servicios sociales para reforzar la identificación y derivación de los beneficiarios. El objetivo declarado por la Generalitat sería doble: responder al déficit de trabajadores en sectores estratégicos y reducir los espacios de economía sumergida en los que hoy quedan atrapados muchos migrantes sin papeles.
La medida, sin embargo, ha suscitado reacciones encontradas incluso antes de su aprobación formal. Las patronales la consideran una respuesta pragmática a una necesidad estructural de la economía catalana. Recuerdan que numerosas empresas llevan meses alertando de dificultades para cubrir determinadas vacantes y sostienen que una parte del crecimiento económico y del sostenimiento del sistema de cuidados dependerá en los próximos años de la incorporación de trabajadores extranjeros. A su juicio, mantener fuera del mercado regular a miles de personas ya presentes en el territorio solo favorece la precariedad y la competencia desleal.
Frente a esa visión, partidos de la oposición y algunas plataformas vecinales advierten de que una medida de este tipo podría enviar una señal de permisividad y tensionar aún más barrios con problemas de acceso a la vivienda, saturación escolar y presión sobre la atención primaria. También cuestionan que la administración disponga de medios suficientes para verificar antecedentes, prevenir fraudes documentales o garantizar que quienes entren en el programa cumplan efectivamente los requisitos. "No se puede convertir una necesidad laboral en un atajo político", resumió un portavoz parlamentario crítico con el plan.
La discusión no se limita al terreno económico. El refuerzo de controles previsto en el borrador ha sido interpretado por sindicatos policiales como un reconocimiento implícito de que el aumento de llegadas y la falta de coordinación institucional generan zonas grises en materia de seguridad. Aunque los datos oficiales no permiten establecer una relación automática entre inmigración y delincuencia, el debate público se ha intensificado en los últimos meses cada vez que se producen episodios de reincidencia o conflictos en equipamientos de acogida.
Entidades sociales y ONG, por su parte, reclaman separar esas situaciones del fenómeno migratorio en su conjunto y recuerdan que la mayoría de personas extranjeras que llegan a España lo hacen para trabajar y estabilizar su vida. Aun así, admiten que la integración ya no puede plantearse solo como una cuestión humanitaria, sino también como un reto cultural y cívico. La exigencia de formación lingüística y conocimiento básico de normas de convivencia, apuntan, puede contribuir a reducir recelos si va acompañada de recursos reales y no de un enfoque punitivo.
El plan, todavía abierto a cambios, amenaza con convertirse en uno de los grandes focos políticos de la primavera catalana. Sobre la mesa no solo está cómo gestionar la inmigración, sino qué modelo de país quiere construir Catalunya ante una realidad demográfica que ya forma parte de su presente.`,
    },
  },
  {
    id: "climate_change",
    label: "Climate change",
    article: {
      type: "news_article",
      headline:
        "Más de un centenar de países pactan en Ginebra recortar un 45% las emisiones pese a las reticencias de las grandes potencias",
      source: "Reuters",
      agent_summary: "112 países firmaron en Ginebra un acuerdo climático que exige reducir las emisiones un 45% antes de 2040 y poner fin a la construcción de nuevas centrales de carbón en 2035. El pacto crea un fondo de 120.000 millones de dólares para apoyar la transición energética en países en desarrollo. India y Rusia se abstuvieron; EE.UU. firmó con matices. Los expertos lo califican de histórico pero advierten de que carece de mecanismos sancionadores suficientes.",
      body: `Un total de 112 Estados suscriben un acuerdo "histórico, aunque insuficiente", que prevé el fin de la nueva infraestructura de carbón en 2035 y la creación de un fondo de 120.000 millones para apoyar a los países en desarrollo.
Tras dos semanas de negociaciones al límite en la Cumbre del Clima de la ONU celebrada en Ginebra, la comunidad internacional ha logrado cerrar un acuerdo de amplio alcance. Un bloque de 112 países firmó este viernes un pacto pionero que eleva de forma sustancial las ambiciones de descarbonización global.
El texto establece compromisos vinculantes para reducir las emisiones de gases de efecto invernadero en un 45% de aquí a 2040, una meta diseñada para hacer compatibles los objetivos climáticos con los compromisos industriales ya asumidos por los Estados firmantes. Para los expertos, el acuerdo marca un punto de inflexión, aunque deja abiertos interrogantes clave sobre su aplicación.
El documento se apoya en dos pilares centrales. Por un lado, la creación de un fondo de transición de 120.000 millones de dólares destinado a financiar el salto de las economías en desarrollo hacia las energías renovables. Por otro, el compromiso de poner fin a la construcción de nuevas centrales de carbón en 2035.
Este calendario ha sido decisivo para sumar al consenso a potencias como Alemania o China, al permitirles completar su planificación energética actual antes de cerrar definitivamente la expansión del carbón. El acuerdo refuerza además los mecanismos de control, con informes trimestrales de emisiones para los países del G20 y protocolos comunes de respuesta ante desastres climáticos.
India, Rusia y Estados Unidos marcan distancias.
El consenso no ha sido total. India y Rusia se abstuvieron en la votación final, apelando a la defensa de su soberanía nacional y al impacto económico que estas medidas tendrían sobre sus industrias pesadas. Estados Unidos sí firmó el texto, aunque introdujo matices que siembran dudas sobre su ejecución real, especialmente en lo relativo al carácter vinculante de las inspecciones internacionales en su territorio.
Optimismo contenido entre los expertos.
El anuncio ha sido recibido con una mezcla de esperanza y escepticismo por parte de organizaciones ecologistas y analistas consultados por este diario. Greenpeace califica el pacto de "histórico, aunque imperfecto", mientras que plataformas como Climate Action Network (CAN) alertan del riesgo de que el acuerdo quede en papel mojado si no se refuerzan los mecanismos sancionadores.
A falta de herramientas que garanticen el cumplimiento, advierten, el compromiso podría quedar reducido a una declaración política sin efectos reales sobre la trayectoria global de emisiones.
Oportunidades y retos para España.
Para España, que se ha consolidado como uno de los referentes europeos en transición energética —con más del 50% de su mix eléctrico procedente ya de fuentes limpias—, el fondo de 120.000 millones abre una oportunidad para sus empresas líderes en los sectores eólico y fotovoltaico.
No obstante, el horizonte de descarbonización fijado por el acuerdo obliga a una reconversión acelerada que podría tensionar la competitividad de la industria pesada nacional frente a mercados con menores exigencias climáticas, si no se acompaña de medidas de protección y apoyo a escala europea.`,
    },
  },
]

export function getNewsTemplateById(id: string): NewsTemplateOption | undefined {
  return NEWS_TEMPLATE_OPTIONS.find((option) => option.id === id)
}


export function createSeedFromTemplate(id: string): SeedArticle | undefined {
  const template = getNewsTemplateById(id)
  if (!template) return undefined
  return {
    ...template.article,
    template_id: template.id,
  }
}
