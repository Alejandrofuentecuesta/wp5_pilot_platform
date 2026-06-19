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
        "España supera los 6,9 millones de residentes extranjeros y sitúa el debate migratorio en el centro de la agenda política",
      source: "Reuters",
      agent_summary: "El censo del INE a 1 de enero de 2025 registra un récord de 6,9 millones de residentes extranjeros en España (14,1% del total), mientras las llegadas irregulares cayeron un 42%. El fenómeno genera lecturas muy diversas: economistas y patronales destacan su aportación al crecimiento del PIB y las pensiones frente a la baja natalidad, mientras que la presión demográfica causa tensiones en servicios públicos y vivienda de ciertas zonas. En el Congreso, el debate está muy polarizado entre la exigencia de mayores controles de la oposición y la defensa de la acogida por parte del Gobierno, mientras sindicatos y ONG reclaman velar por los derechos laborales y humanos.",
      body: `El censo del INE a 1 de enero de 2025 registra 6.911.971 personas de nacionalidad extranjera, el 14,1% de la población total, mientras las llegadas irregulares cayeron un 42% en ese mismo año. Economistas, partidos políticos, sindicatos, ayuntamientos y organizaciones sociales ofrecen lecturas radicalmente distintas sobre las consecuencias y la gestión del fenómeno.
España ha alcanzado un nuevo récord en el número de residentes extranjeros. Según el censo anual del Instituto Nacional de Estadística (INE), a 1 de enero de 2025 vivían en el país 6.911.971 personas de nacionalidad extranjera, el 14,1% de una población total que supera por primera vez los 49 millones de habitantes. El incremento respecto al año anterior fue del 6,3%, una velocidad de crecimiento muy superior a la de la población española, que apenas creció un 0,2%. Las nacionalidades más numerosas son la marroquí (969.000 personas), la colombiana (677.000) y la rumana (609.000).
Este crecimiento de la población extranjera residente convive con una dinámica muy distinta en las llegadas irregulares. Según el Ministerio del Interior, en 2025 accedieron a España de forma irregular 36.775 personas, un 42,6% menos que en 2024, cuando se registraron 64.000 entradas. La mayor caída se produjo en Canarias, donde las llegadas por vía marítima se redujeron un 62%. En sentido contrario, las entradas terrestres por Ceuta y Melilla aumentaron un 45%.
El fenómeno no es homogéneo. Una parte importante de la población extranjera llegó al país por vías regulares para cubrir vacantes en sectores como la agricultura, la construcción, la hostelería o los cuidados. España es también destino de inmigración cualificada procedente de América Latina y de otros países de la Unión Europea, especialmente en el sector tecnológico y sanitario. Otra parte transita durante períodos prolongados en una situación administrativa sin resolver.
UN MOTOR ECONÓMICO CON TENSIONES VISIBLES
Para economistas y patronales, el balance global es positivo. España tiene una de las tasas de natalidad más bajas de Europa y una pirámide poblacional que, sin aportación migratoria, comprometería la sostenibilidad del sistema de pensiones y la disponibilidad de mano de obra en sectores clave. Estudios del Banco de España coinciden en señalar que la inmigración ha contribuido de forma significativa al crecimiento del PIB en los últimos años y que numerosas empresas, especialmente en el sector agrícola y de servicios, no podrían funcionar sin trabajadores extranjeros.
Sin embargo, esa misma presión demográfica genera tensiones en algunos territorios. En zonas de alta concentración de llegadas —las Islas Canarias, determinados barrios de las grandes ciudades, municipios agrícolas del litoral mediterráneo— los servicios públicos de salud, educación y vivienda acusan una sobrecarga que las administraciones locales no siempre están en condiciones de asumir. Varios alcaldes de municipios de distinto signo político han reclamado mayor coordinación institucional y más recursos para gestionar la acogida.
EL DEBATE POLÍTICO, CADA VEZ MÁS POLARIZADO
En el Congreso, la inmigración se ha convertido en uno de los ejes de confrontación más agudos de la legislatura. El Gobierno defiende que España ha respondido con responsabilidad a un fenómeno de alcance europeo, destaca los programas de integración en marcha y apela a los valores constitucionales de solidaridad. El partido en el poder subraya además el papel de España como país de tránsito en la política migratoria europea y las limitaciones que impone el marco comunitario para actuar unilateralmente en fronteras y expulsiones.
La oposición, con matices según la formación, exige endurecer los controles fronterizos, agilizar los procedimientos de devolución de personas sin derecho a asilo y revisar los convenios de acogida con países de origen. Partidos situados en el extremo derecho del espectro han hecho de la inmigración su principal argumento electoral, vinculando el aumento de la población extranjera con la presión sobre los servicios públicos y, de forma más controvertida, con indicadores de inseguridad ciudadana. Los datos policiales no avalan una correlación directa entre inmigración y delincuencia, pero el debate persiste en la esfera pública.
SINDICATOS Y ONG, ANTE UNA REALIDAD COMPLEJA
Los sindicatos mayoritarios mantienen una posición que intenta conciliar la defensa de los derechos laborales de los trabajadores migrantes —frecuentemente empleados en condiciones precarias— con la preocupación por el dumping salarial que puede producirse en sectores con alta concentración de mano de obra irregular. Para CCOO y UGT, la respuesta no pasa por cerrar fronteras sino por reforzar la inspección laboral y garantizar que todos los trabajadores, con independencia de su origen, tengan las mismas condiciones.
Las organizaciones humanitarias —Cruz Roja, Cáritas, ACNUR— reclaman un enfoque que distinga entre distintos tipos de migración: refugiados que huyen de conflictos o persecuciones, migrantes económicos en busca de una vida mejor, y víctimas de redes de tráfico de personas. Alertan del riesgo de que el debate político amalgame realidades muy distintas y acabe derivando en medidas que vulneren derechos fundamentales.
UNA SOCIEDAD DIVIDIDA, PERO NO UNIFORME
Las encuestas reflejan una opinión pública que no se deja reducir a posiciones simples. La mayoría de los españoles reconoce que la inmigración aporta valor económico y cultural al país, pero también expresa preocupación por la capacidad del sistema para integrar a las personas que llegan, especialmente en un contexto de tensión en el mercado de la vivienda y de listas de espera en la sanidad pública. La percepción varía notablemente según la edad, el territorio y la experiencia directa de convivencia con población inmigrante.`,
    },
  },
  {
    id: "climate_change",
    label: "Climate change",
    article: {
      type: "news_article",
      headline:
        "España cierra 2025 como el tercer año más cálido de su historia y aviva un debate sobre el clima que divide a la sociedad",
      source: "Reuters",
      agent_summary: "España cierra 2025 como el tercer año más cálido de su historia (1,1 grados por encima de la referencia de la AEMET), con sequías, tres olas de calor y graves incendios forestales (354.000 ha quemadas). Aunque el diagnóstico científico es claro, el debate político está muy polarizado entre defensores de acelerar la descarbonización y sectores críticos que acusan el discurso de alarmismo climático. El sector agrario (ASAJA, COAG, UPA) admite los extremos climáticos pero rechaza las normativas de la PAC por considerarlas un lastre burocrático y una fuente de competencia desleal frente a terceros países con menores costes (como Marruecos).",
      body: `La AEMET confirma que la temperatura media de 2025 fue 1,1 grados por encima de la referencia histórica, con tres olas de calor y máximos de casi 46 grados. El diagnóstico científico es unánime, pero el debate político sobre sus causas, su alcance y las respuestas necesarias está lejos de serlo.
España ha cerrado 2025 como el tercer año más cálido desde que existen registros instrumentales, según el informe anual publicado por la Agencia Estatal de Meteorología (AEMET). La temperatura media fue de 15 grados centígrados, 1,1 grados por encima del período de referencia 1991-2020, lo que sitúa 2025 al nivel de 2024 y por detrás únicamente de 2022 y 2023. Los once años más cálidos de toda la serie histórica española se han registrado en el siglo XXI. El año 2025 estuvo marcado por tres grandes olas de calor entre junio y agosto, con temperaturas que alcanzaron los 45,8 grados en Jerez de la Frontera el 17 de agosto.
Las consecuencias de esta tendencia son perceptibles en el territorio desde hace décadas. Los glaciares del Pirineo han perdido más del 88% de su superficie desde mediados del siglo XIX, pasando de 52 masas glaciares a apenas 19 en la actualidad, según datos publicados en la revista científica Pirineos del CSIC. Los incendios forestales alcanzaron en 2025 dimensiones históricas: se quemaron más de 354.000 hectáreas, el triple de la media de la última década, convirtiendo ese año en el más devastador para los bosques españoles en tres décadas. Las precipitaciones, aunque en 2025 se situaron en el 109% de la media histórica, presentan una distribución cada vez más irregular: sequías prolongadas en el interior y episodios torrenciales en el litoral, como los 174,8 litros por metro cuadrado registrados en Tortosa en un solo día en octubre.
LA CIENCIA, CON UN DIAGNÓSTICO CONSOLIDADO
Para la comunidad científica, la tendencia no admite dudas. El Panel Intergubernamental sobre Cambio Climático (IPCC) sostiene que la responsabilidad humana en el calentamiento global es "inequívoca" y que sus consecuencias sobre los ecosistemas, la salud pública y la economía serán crecientes si no se producen cambios estructurales en los sistemas energético, alimentario y de transporte. Investigadores del CSIC subrayan que España es uno de los países europeos más vulnerables al cambio climático por su posición geográfica, su dependencia hídrica y la extensión de su litoral.
UN DEBATE POLÍTICO QUE NO SOLO VERSA SOBRE SOLUCIONES
En el terreno político, el debate va más allá de cómo responder al fenómeno: también alcanza a su propia interpretación. El Gobierno defiende el consenso científico y lo sitúa como base de su política energética, destacando que más del 50% del mix eléctrico español procede ya de fuentes renovables. Para el Ejecutivo, el reto es acelerar la descarbonización sin sacrificar la competitividad industrial ni el empleo.
Desde otras formaciones políticas se cuestiona el alcance o la urgencia del problema. Se denuncia lo que califican de "alarmismo climático" y se advierte de las consecuencias que las políticas verdes tienen sobre el empleo industrial y el sector agrario. Estas voces no niegan necesariamente que el clima cambie, pero rechazan que el origen sea exclusivamente humano o que las respuestas propuestas sean las adecuadas.
EL CAMPO, ENTRE LA VULNERABILIDAD Y EL RECHAZO A LAS NORMAS
El sector agrario ocupa un lugar especialmente tenso en este debate. Las tres grandes organizaciones agrarias españolas —ASAJA, COAG y UPA— reconocen que la sequía y los fenómenos meteorológicos extremos son cada vez más frecuentes e intensos, y han reclamado fondos extraordinarios para compensar las pérdidas provocadas por el cambio climático. Al mismo tiempo, se oponen frontalmente a buena parte de las normativas medioambientales que la Unión Europea exige como condición para recibir las ayudas de la Política Agraria Común (PAC).
Su argumento central es el de la competencia desleal: los productores españoles deben cumplir requisitos ambientales y laborales que encarecen sus costes, mientras compiten en el mismo mercado con importaciones procedentes de países con normativas mucho menos exigentes. En el caso del tomate, las ventas españolas en la UE cayeron un 33% entre 2015 y 2025, mientras que las importaciones de Marruecos crecieron un 71% hasta alcanzar 1,4 millones de toneladas, procedentes de un país donde, según las organizaciones agrarias, el salario mínimo agrícola es de 0,98 euros por hora frente a los 9,74 euros que rige en España. Para el sector, esto convierte las exigencias medioambientales europeas en un lastre competitivo que penaliza al agricultor local sin reducir las emisiones globales.
A ello se suma la crítica a la burocracia. Las organizaciones agrarias denuncian que los trámites asociados a los ecorregímenes y a la condicionalidad reforzada de la PAC generan costes administrativos que muchas explotaciones pequeñas y medianas no pueden asumir, y que alejan a los agricultores de unas ayudas que en teoría deberían facilitarles la transición.
LA SOCIEDAD CIVIL, ENTRE LA ALARMA Y EL ESCEPTICISMO
Las organizaciones ecologistas alertan de que el ritmo de cambio institucional es insuficiente frente a la velocidad del deterioro climático, e insisten en que los compromisos adquiridos por los gobiernos no bastan si no se acompañan de medidas de protección y apoyo a escala europea. Greenpeace y WWF subrayan que cada año de retraso estrecha el margen de actuación.
Pero junto a esa movilización coexiste una percepción de saturación en amplias capas de la población. Encuestas del Centro de Investigaciones Sociológicas (CIS) apuntan a que el cambio climático figura entre las principales preocupaciones de los españoles, pero también que crece la desconfianza hacia la capacidad real de los gobiernos para gestionarlo y una sensación de impotencia individual frente a la magnitud del problema.`,
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
