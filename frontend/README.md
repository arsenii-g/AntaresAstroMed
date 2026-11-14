# Frontend

Dueño: Roberto. Vue 3 + Vite, sin más dependencias.

Dos pestañas, como en el boceto:

- **Daily check**: el chequeo guiado (ánimo de 1 a 5, tensión y glucosa). Lo manda a `POST /api/v1/checks` (contrato ②). Lo que no se rellena va como `null`.
- **Status**: a la izquierda, el cuerpo del tripulante. A la derecha, el aviso de color, los problemas, las recomendaciones, los números en vivo y la cabina.

## Cómo se pinta el cuerpo

La web **no calcula niveles**: pinta lo que manda el motor en la evaluación ③.

| Nivel | Color | Aviso |
|---|---|---|
| 0 | Verde | All clear |
| 1 | Ámbar | Caution |
| 2 | Naranja | Warning: avisar al oficial médico |
| 3 | Rojo | Alert!: aparece el resumen para Tierra |
| `null` | Gris rayado | No data (nunca verde) |

| Zona | Sistema | Si está en ámbar o peor |
|---|---|---|
| Cabeza | `neuro` | Se dibuja el cerebro |
| Tronco | `cardiovascular` | Se dibuja el corazón (late en naranja y rojo) |
| Brazos y piernas | `musculoskeletal` | Se dibuja el esqueleto |
| Tarjeta "Cabin" | `environment` | Borde y etiqueta del color del nivel |

Cada zona lleva el color de su sistema, y el halo de fondo y la línea de la cabecera llevan el de `overall_level`. Al pulsar una zona, la lista de problemas muestra solo los `reasons` de ese sistema. Los textos del motor salen en inglés y sin traducir.

## Gráficas de tendencia

Hay una gráfica por cada elemento de `trends`. Van primero las que cruzan antes un umbral.

El motor no manda los puntos medidos, sino la recta de mínimos cuadrados (`risk/trends.py`). Se reconstruye con `projected_7d` y `slope_per_day`:

```
valor(x) = projected_7d − 7·slope_per_day + slope_per_day·x      (x = días respecto a hoy)
```

- De −7 días a hoy se pinta el ajuste (línea continua), y de hoy a +7 días la proyección (discontinua).
- El umbral es una línea del color del nivel al que llevaría (`threshold_level`), con un punto donde la recta lo cruza (`crosses_threshold_in_days`).
- Al pasar el ratón se ve el valor de la recta en ese día.

Si queremos pintar también los puntos medidos, la API tendrá que mandarlos aparte.

## Arrancar

```bash
cd frontend
npm install
npm run dev         # web en http://localhost:5173, habla con la API en http://localhost:8000
```

La web no trae datos inventados: todo lo que pinta llega de la API. Sin datos, el cuerpo sale gris ("No data"). Sin nadie fichado, avisa de que espera a que alguien pase la tarjeta.

### Backend de prueba, mientras no esté la API

`dev-backend/server.py` es un backend **de prueba**, no la API del proyecto (esa es `api/`). Recibe ① y ②, llama a `risk.evaluate()` y emite ④ por `/ws` y `/latest`, todo en memoria. Hacen falta tres terminales, desde la raíz del repo:

```bash
python -m venv .venv && .venv/Scripts/pip install -r frontend/dev-backend/requirements.txt   # una vez

# 1. Backend de prueba (SPACEHEALTH_DEMO=1: inactividad a 30 s)
SPACEHEALTH_DEMO=1 .venv/Scripts/python -m uvicorn server:app --app-dir frontend/dev-backend --port 8000
# 2. Web en modo real
cd frontend && npm run dev            # abre http://localhost:5173
# 3. Simulador de la placa (o la placa de verdad apuntando a :8000)
.venv/Scripts/python -m simulator.simulate --scenario demo --history-days 7 --url http://localhost:8000
```

Con el guion `demo` pasa lo siguiente:

- Al principio nadie está fichado.
- A los 15 s entra el tripulante 1.
- Se queda quieto hasta que salta el ámbar por inactividad.
- Hace flexiones.
- A los 100 s entra el tripulante 2 con el pulso en rojo, y la web cambia de perfil sola.

El chequeo de la pestaña "Daily check" también pasa por el motor.

Sin el paso 3, el backend arranca vacío y la web no muestra nada: es lo esperado.

Configuración en `.env.local` (copia `.env.example`). Para elegir tripulante al abrir, usa `?crew=F3786E09` en la URL.

## Qué espera de la API (pendiente de confirmar con Jesus)

- **WebSocket** en `/ws` (`VITE_WS_PATH`). Mensajes `{"type", "data"}`:
  - `telemetry`: actualiza los números en vivo.
  - `event`: un `crew_checkin` cambia de tripulante; un `exercise_summary` actualiza "Last push-ups".
  - `assessment`: actualiza colores, problemas y recomendaciones.

  Solo se usan los mensajes del `crew_id` en pantalla, y se descartan los que llegan con un `ts` más antiguo que el que ya se muestra. Si se cae, reconecta a 1, 2, 4… s (hasta 30 s).
- **`GET /api/v1/crew/{id}/latest`**: al abrir, al cambiar de tripulante y al reconectar. Acepta `{ "telemetry": …, "assessment": … }` o directamente una evaluación ③. Un 404 se toma como "sin datos todavía".
- **`POST /api/v1/checks`**: 2xx o 409 se dan por buenos.
- Si la API pide `X-API-Key` también a la web, ponla en `VITE_API_KEY`. Acaba en el JavaScript del navegador: vale para la demo, no es un secreto.

## Pendiente

- Endpoint para enviar el `earth_summary`. De momento el botón lo copia al portapapeles.
