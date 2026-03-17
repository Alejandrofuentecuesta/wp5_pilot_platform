# WP5 Pilot Platform v2 — Arranque desde cero

Este README está pensado para alguien que **parte de cero**: máquina nueva, sin nada preparado, y quiere levantar la plataforma localmente usando este repositorio.

## 1) Requisitos previos (instalar desde cero)

### 1.1 Git
- Descarga e instala Git: https://git-scm.com/downloads
- Verifica:

```bash
git --version
```

### 1.2 Docker Desktop (incluye Docker Compose)
- Instala Docker Desktop: https://docs.docker.com/get-docker/
- Abre Docker Desktop y espera a que esté en estado “running”.
- Verifica:
```bash
docker --version
docker compose version
```
> Si `docker compose version` falla, actualiza Docker Desktop.
---

## 2) Clonar el repositorio
git clone <URL_DEL_REPO>
cd wp5_pilot_platform_v2
```
Si ya lo tienes clonado, entra en la carpeta del proyecto:

```bash
cd wp5_pilot_platform_v2
---
## 3) Crear tu archivo de entorno
Copia la plantilla de variables:

Abre `.env` y completa al menos:
- `ADMIN_PASSPHRASE` (obligatorio para entrar al panel admin)
- API keys del proveedor LLM que vayas a usar (`ANTHROPIC_API_KEY`, `HF_API_KEY`, `GEMINI_API_KEY`, etc.)

Opcional (si tienes puertos ocupados):
- `BACKEND_PORT` (por defecto 8000)
- `FRONTEND_PORT` (por defecto 3000)

---
## 4) Levantar toda la plataforma
Desde la raíz del repo:

```bash
docker compose up --build
```

Esto arranca:
- PostgreSQL
- Redis
- Backend (API)
- Frontend (web + admin)

Cuando termine de arrancar:
- Frontend: `http://localhost:3000` (o el valor de `FRONTEND_PORT`)
- Admin: `http://localhost:3000/admin`
- Backend: `http://localhost:8000` (o el valor de `BACKEND_PORT`)

---

## 5) Primer acceso al Admin

1. Abre `http://localhost:3000/admin`
2. Introduce el `ADMIN_PASSPHRASE` que pusiste en `.env`
3. Configura el experimento desde el wizard
---
## 6) Comandos básicos de operación
### Ver logs
docker compose logs -f
### Parar servicios
```bash
docker compose down
### Parar y borrar volúmenes (reset completo de datos locales)
```bash
docker compose down -v
```
### Reiniciar reconstruyendo imágenes
```bash
docker compose up -d --build
```
---
## 7) Problemas comunes
### Error: `Bind for 0.0.0.0:8000 failed: port is already allocated`
Tienes el puerto 8000 ocupado por otro proceso.
Solución:
1. Edita `.env`
2. Cambia, por ejemplo:
   - `BACKEND_PORT=8010`
   - `FRONTEND_PORT=3001` (si también tienes ocupado el 3000)
3. Vuelve a arrancar:
```bash
docker compose up --build
```
### Docker no arranca
- Asegúrate de que Docker Desktop está abierto y en estado running.
- Reinicia Docker Desktop.
### Cambié `.env` y no veo cambios
Recrea contenedores:
```bash
docker compose up -d --force-recreate
```
---
## 8) Checklist rápido (de cero a funcionando)
1. Instalar Git ✅
2. Instalar Docker Desktop ✅
3. Clonar repo ✅
4. `cp .env.example .env` ✅
5. Rellenar `ADMIN_PASSPHRASE` + API key(s) ✅
6. `docker compose up --build` ✅
7. Entrar en `http://localhost:3000/admin` ✅
Listo.
â””â”€â”€ README.md
```

## Citation

If you use this platform in your research, please cite it:

> Kiddle, R. & van Atteveldt, W. (2026). *STAGElab: A Platform for Agent-Generated Experiments* [Software]. GitHub. https://github.com/Rptkiddle/wp5_pilot_platform

A methods paper is forthcoming â€” this section will be updated with a full reference when available.

### References

- Kim, Y., Gu, K., Park, C., et al. (2025). *Towards a Science of Scaling Agent Systems*. arXiv preprint [arXiv:2512.08296](https://arxiv.org/abs/2512.08296).
- Vezhnevets, A. S., Agapiou, J. P., Aharon, A., et al. (2023). *Generative agent-based modeling with actions grounded in physical, social, or digital space using Concordia*. arXiv preprint [arXiv:2312.03664](https://arxiv.org/abs/2312.03664).

GitHub also provides a "Cite this repository" button (powered by [`CITATION.cff`](CITATION.cff)).

## License

This project is licensed under the [GNU Affero General Public License v3.0](https://www.gnu.org/licenses/agpl-3.0.html) â€” you are free to use, modify, and distribute this software, provided that any derivative work is also released under the same license and includes attribution to the original author.

### Arranque directo desde el escritorio

Si quieres iniciar la plataforma con doble clic desde el escritorio, usa los launchers incluidos:

- **Linux:** `scripts/start-linux.sh`
- **macOS:** `scripts/start-macos.command`
- **Windows:** `scripts/start-windows.bat`

Pasos mínimos:
1. Ejecuta una vez el launcher de tu sistema.
2. Se creará `.env` si no existe y se levantará Docker automáticamente.
3. Crea un acceso directo en el escritorio al launcher y úsalo para futuros arranques.

> Requisito: Docker + Docker Compose instalados.
> Si `8000` o `3000` están ocupados, cambia `APP_PORT` y/o `FRONTEND_PORT` en `.env`.
