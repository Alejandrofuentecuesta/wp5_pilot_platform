"use client"

/**
 * The deception debriefing shown whenever the platform itself ends a
 * participant's session before their allotted time (safety intervention,
 * a researcher closing the session from the Safety tab, etc.) — cases where
 * the participant never reaches the external survey's own debriefing page.
 * Normal completion and a self-initiated exit are not routed through this
 * component; they rely on the survey's existing debriefing.
 */
export default function DebriefingNotice() {
  return (
    <div className="space-y-3 text-left text-sm leading-6 text-secondary">
      <p>
        Antes de terminar, queremos contarte algo importante sobre el estudio de investigación.
      </p>
      <p>
        Todos los participantes con los que interactuaste eran bots programados con IA, no
        personas reales. Esto fue necesario porque el objetivo del estudio es entender cómo
        reaccionamos ante distintos tipos de conversación online (más o menos civiles, más o
        menos afines a nuestras opiniones) de forma controlada y comparable entre todos los
        participantes, algo que no sería posible si dependiéramos de personas reales, cuyo
        comportamiento no podríamos controlar ni repetir de la misma manera. Decírtelo desde el
        principio habría cambiado tu forma de participar y habría invalidado los resultados.
      </p>
      <p>
        Estos bots o agentes de IA operaban de acuerdo con condiciones conversacionales asignadas
        experimentalmente (más o menos civiles, más o menos afines a nuestras opiniones). Los
        comentarios potencialmente ofensivos fueron generados como parte del diseño de
        investigación y no representan juicios personales de personas reales ni de ningún miembro
        del equipo de investigación.
      </p>
      <p>
        Tu forma de responder durante la conversación es completamente válida y útil para la
        investigación. No hay nada &quot;erróneo&quot; en haber creído que podían ser personas
        reales; de hecho, era la reacción esperada y necesaria para el estudio.
      </p>
      <p>
        Sobre tus datos: recuerda que todos los datos recopilados serán seudonimizados, de forma
        que toda la información personal y sensible se separará de los datos principales y se
        almacenará de forma segura, con acceso restringido al equipo de investigación. En ningún
        momento se compartirá información que permita identificarte personalmente.
      </p>
      <p>
        De nuevo, agradecemos enormemente tu participación en este estudio. ¡Has contribuido al
        avance de la ciencia y a mejorar la calidad de nuestros entornos online!
      </p>
    </div>
  )
}
