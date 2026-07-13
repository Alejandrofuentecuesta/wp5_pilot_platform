# Generador de hilos para el Turing Test

`generate_turing_threads.py` regenera los hilos ficticios del experimento del
Turing Test usando el pipeline STAGE actual de la plataforma, y deja un visor
estático con los hilos reales y los regenerados listos para comparar.

## Qué hace

1. **Scrapea** los hilos originales (reales y ficticios, longitudes 8 y 16) de la
   página estática del Turing Test final
   (`alexcasadevall.github.io/proves-posts-turing-test/Turing Final`) y guarda una
   copia en `scraped/`.
2. **Copia los hilos reales tal cual** (no se regeneran) y comprueba que en la
   fuente original los hilos de 8 son prefijo exacto de los de 16
   (`prefix_report.json`).
3. **Regenera cada hilo ficticio** con el orquestador STAGE: genera 16 mensajes
   por hilo y escribe dos ficheros — el de longitud 16 y el de longitud 8, que es
   el **prefijo (primeros 8 mensajes) del de 16** (marcado con
   `derived_from_16: true` en los metadatos). No son dos generaciones distintas.
4. Descarga el **visor estático** (`index.html`, `viewer.html`, `estils.css`)
   adaptado a 4 pestañas (Reals/Ficticis × 8/16) y escribe **diagnósticos** por
   hilo y agregados.

Son 21 hilos: 8 de canvi climàtic (`clim_1–8`) y 13 de immigració (`imm_1–13`).

## Cómo genera cada hilo

| Rol | Proveedor / modelo (por defecto) | Temperatura | Max tokens |
|---|---|---|---|
| Director | Anthropic `claude-sonnet-4-6` | 0.7 | 1024 |
| Performer | BSC `incivility` (versión `v1`) | 1.1 (top_p 0.92) | 96 |
| Moderator | Anthropic `claude-haiku-4-5` | 0.2 | 512 |
| Classifier | Anthropic `claude-haiku-4-5` | 0.2 | 256 |

- **Tratamiento**: `mix_mix`, con los presets 3×3 del frontend
  (`CHATROOM_CONTEXT_3X3`, `INCIVILITY_FRAMEWORK_3X3`, `ECOLOGICAL_VALIDITY_3X3`
  y los criterios de validez interna de `mix_mix`), leídos directamente de
  `frontend/lib/treatment-presets.ts`.
- **Agentes**: modo pool. Los personajes salen de
  `frontend/lib/agent-pool-presets.ts` (`CLIMATE_CHANGE_AGENT_POOL` /
  `IMMIGRATION_AGENT_POOL`) y se asignan rotando un patrón de 8 plantillas:
  pro/anti-tema × civil/incivil. Los **nombres visibles** se reutilizan de los
  hilos ficticios antiguos (`--names-source fictic`, por defecto) o de los
  reales (`real`).
- **Noticia**: el `post_original` del hilo real se inyecta en el contexto del
  chatroom, de modo que los agentes comentan la misma noticia que en el hilo
  real equivalente.
- **Política de longitud**: agentes civiles 5–28 palabras por mensaje;
  inciviles 3–22. El performer además está limitado por `--performer-max-tokens`.
- **Likes**: el orquestador aplica auto-likes con probabilidad
  `--auto-like-probability` (0.12 por defecto).
- **Orquestador**: `evaluate_interval=5`, `action_window_size=5`,
  `performer_memory_size=3`, `boost_replies_mentions=True`, participante
  simulado "Alex" con postura `pro_topic`.

### Reproducibilidad

La semilla de cada hilo es determinista: `--seed` (4200 por defecto) `+ número`
para clima y `+ 1000 + número` para inmigración (`clim_1` → 4201,
`imm_3` → 5203). Todos los parámetros de la ejecución quedan registrados en el
campo `generation_metadata` de cada JSON generado.

## Requisitos

- Ejecutarlo desde la **imagen Docker del backend** (usa sus dependencias LLM).
- Un `.env` con `ANTHROPIC_API_KEY` y `BSC_API_KEY` (o `BSC_API_KEYS_FILE`;
  opcionalmente `BSC_API_BASE_URL`).
- Acceso de red a la página estática de origen y al endpoint BSC. Antes de
  generar hace un **preflight** contra el performer BSC y aborta si no responde
  (se puede saltar con `--skip-bsc-preflight`).
- El repo completo montado en el contenedor: el script lee presets de
  `frontend/lib/`, y el montaje por defecto del servicio `app` solo incluye
  `backend/`.

## Uso

```bash
# Generación completa (21 hilos, ~1 h según latencia de los modelos)
docker compose run --rm -v "$PWD":/workspace -w /workspace app \
  python backend/scripts/generate_turing_threads.py

# Solo unos hilos concretos
docker compose run --rm -v "$PWD":/workspace -w /workspace app \
  python backend/scripts/generate_turing_threads.py --only clim_1,imm_11

# Solo scrapear los originales, sin generar nada
docker compose run --rm -v "$PWD":/workspace -w /workspace app \
  python backend/scripts/generate_turing_threads.py --scrape-only
```

Por defecto **no sobrescribe** hilos ya generados (los salta); usa `--force`
para regenerarlos.

### Parámetros

| Flag | Por defecto | Descripción |
|---|---|---|
| `--output-dir` | `results/turing_test_regenerated` | Carpeta de salida |
| `--seed` | `4200` | Semilla base (ver reproducibilidad) |
| `--only` | — | IDs concretos, p. ej. `clim_1,imm_11` |
| `--limit` | `0` | Genera solo los N primeros hilos |
| `--force` | off | Regenera aunque ya exista la salida |
| `--scrape-only` | off | Solo descarga los hilos originales |
| `--names-source` | `fictic` | Nombres de los agentes: `fictic` o `real` |
| `--participant-name` | `Alex` | Nombre del participante simulado |
| `--participant-stance` | `pro_topic` | Postura del participante |
| `--director-model` | `claude-sonnet-4-6` | Modelo del director |
| `--haiku-model` | `claude-haiku-4-5` | Modelo de moderator y classifier |
| `--performer-model` | `incivility` | Modelo BSC del performer |
| `--bsc-model-version` | `v1` | Versión del modelo BSC (`v1`/`v2`) |
| `--performer-temperature` | `1.1` | Temperatura del performer |
| `--performer-top-p` | `0.92` | Top-p del performer |
| `--performer-max-tokens` | `96` | Límite de tokens por mensaje |
| `--auto-like-probability` | `0.12` | Probabilidad de auto-like por turno |
| `--max-turn-attempts` | `80` | Máx. turnos del orquestador por hilo |
| `--humanize` | off | Aplica las reglas de humanización de salida |
| `--skip-bsc-preflight` | off | No comprueba el endpoint BSC antes de generar |

## Salida

```
results/turing_test_regenerated/
├── index.html / viewer.html / estils.css   # visor estático (abrir con un servidor local)
├── reals/{8,16}/<id>.json                  # hilos reales re-scrapeados, sin cambios
├── ficticis/{8,16}/<id>.json               # hilos regenerados (8 = prefijo del 16)
├── scraped/{reals,ficticis}/{8,16}/        # copia cruda de la fuente original
├── diagnostics/<id>.json                   # intentos, nº inciviles, likes, errores por hilo
├── diagnostics_summary.json                # agregado de todos los diagnósticos
└── prefix_report.json                      # verificación de prefijos en la fuente
```

Cada JSON de `ficticis/` incluye `generation_metadata` con la semilla, modelos,
nombres, política de longitud y los avisos del pipeline de esa generación.

> Nota: `results/` está en el `.gitignore`, así que los hilos generados no se
> versionan; solo este script y su documentación.
