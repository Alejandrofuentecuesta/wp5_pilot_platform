# BSC Incivility API

Integracion del modelo de incivilidad del BSC para usarlo como `performer` dentro de la plataforma WP5.

## Que es

Este modelo forma parte de WHAT-IF y se sirve desde una API externa conectada con MareNostrum 5. Esta pensado para generar respuestas cortas con estilo de red social y distintos grados de civilidad/incivilidad.

En la plataforma encaja mejor como:

- `performer`: si quieres que los agentes redacten mensajes con tono mas de foro/red social

No es la mejor opcion para:

- `director`: necesita mas capacidad de planificacion estructurada
- `moderator`: necesita extraccion fiable y limpia
- `classifier`: necesita salida consistente y estructurada

## Endpoint integrado

La plataforma usa el endpoint OpenAI-compatible:

- Base URL por defecto: `http://212.128.226.126/incivility/api/v1`
- Modelo sugerido: `incivility`

La integracion incluye una adaptacion especifica para esta API porque devuelve el texto generado en `reasoning_content` cuando `content` viene vacio.

## Variables de entorno

Anade estas variables a tu `.env`:

```env
BSC_API_KEY=tu_api_key
# opcional
BSC_API_BASE_URL=http://212.128.226.126/incivility/api/v1
```

## Como usarlo en el admin

1. Entra en `http://localhost:3000/admin`
2. Ve al paso `LLM Pipeline`
3. Deja un modelo fuerte como `director`
4. En `performer`, elige:

```text
provider = bsc
model = incivility
```

Valores iniciales razonables:

```text
temperature = 0.7
top_p = 0.9
max_tokens = 256
```

## Limitaciones practicas

- Es un modelo afinado para respuestas cortas, no para razonamiento largo.
- Su tono puede ser mas agresivo o mas tajante que un modelo generalista.
- Funciona mejor cuando el `director` ya ha hecho el trabajo de decidir la accion y el encuadre del mensaje.
- Si el backend remoto del BSC esta arrancando un job en MN5, puede tardar un poco mas en responder.

## API original

La API externa tambien expone:

- `GET /health`
- `POST /generate`
- `POST /v1/chat/completions`

La plataforma WP5 usa solo la via OpenAI-compatible para reutilizar el pipeline actual sin cambiar STAGE.
