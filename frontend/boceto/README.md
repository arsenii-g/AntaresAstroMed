# frontend/boceto/: boceto visual de ArgosMed

Boceto visual de ArgosMed, para que Roberto lo use de referencia y lo complete. Su app en Vue está en la rama `web/body-svg`; este boceto va en su propia carpeta para no chocar con ella. Tiene dos páginas: una portada (`index.html`) y la consola de operaciones (`console.html`), a la que se entra con *Open the console*. Es HTML, CSS y JavaScript sin dependencias ni paso de compilación: funciona sin internet (solo las fuentes vienen de Google Fonts, y si no cargan se usan las del sistema).

## Cómo verlo

Los módulos de JavaScript no cargan abriendo el archivo con doble clic; hace falta un servidor local:

```bash
python3 -m http.server 5173 --directory frontend/boceto
```

Y abrir <http://localhost:5173/console.html>. La consola se conecta a la API (`api/main.py`) en el mismo ordenador, puerto 8000:

```bash
python -m uvicorn api.main:app --port 8000
```

Si la API está en otra máquina: `console.html?api=http://IP:8000`. También admite `&crew=F3786E09` (tripulante seleccionado al abrir) y `&key=...` (cabecera `X-API-Key`; por defecto la de `api/main.py`).

Qué usa de la API: `GET /api/v1/crew/{id}/latest` (estado, nombre y rol) y `GET /api/v1/crew/{id}/telemetry` (líneas de pulso y temperatura) al cargar y al reconectar; el WebSocket `/ws` con mensajes `telemetry`, `event`, `check` y `assessment`; y `POST /api/v1/checks` para el chequeo diario. Si se cae el enlace, la pastilla de arriba dice *NO LINK TO BASE* y reintenta sola (1, 2, 4… s, hasta 30 s).

## Qué hay

| Archivo | Qué es |
|---|---|
| `index.html` | Portada: planeta, explicación en tres pasos y botón a la consola |
| `landing.css`, `js/landing.js` | Estilo y animaciones de la portada |
| `console.html` | Consola, con dos vistas. **Monitor**: tripulación, sistemas, cuerpo, constantes, tendencia, acciones, resumen para Tierra, registro de eventos y enlace con el vehículo. **Daily check**: el formulario del contrato ② |
| `styles.css` | Estilo de la consola. Colores, fuentes y niveles son variables al principio |
| `js/app.js` | Recibe mensajes `{ type, data }` y pinta. También lleva el registro de eventos (cambios de nivel por sistema), el aviso con botón *Acknowledge* y la antigüedad de los datos |
| `js/mock.js` | Datos de ejemplo antiguos; ya no se usan |
| `js/hologram.js` | Cuerpo 3D de puntos con forma de cilindros redondeados, coloreado por sistema; se puede hacer clic y girar |
| `js/planet.js` | Planeta 3D: fondo de la portada y panel *Vehicle link* de la consola (cambia con sus opciones) |
| `js/stage.js` | Bucle de dibujo común a los dos lienzos |

Los niveles se pintan con el atributo `data-level` (`0` verde, `1` ámbar, `2` naranja, `3` rojo, vacío = gris "No data"). Un nivel `null` nunca se pinta en verde.

Decisiones de criterio propio, ajustables en `js/app.js`:

- **Datos viejos** (`STALE_S = 15`): si no llega telemetría en 15 s (3 mensajes de la placa), las constantes se ponen en gris y el enlace dice *NO SIGNAL*.
- **Sin detalles técnicos en pantalla**: la consola es para la tripulación, así que no enseña endpoints, JSON ni el origen de los datos. Solo dice si llegan lecturas del sensor. Con datos de ejemplo, la pastilla de arriba añade *DEMO*, para que nadie confunda la demo con datos reales.
- **Aviso**: sale para nivel 2 o 3. *Acknowledge* lo oculta solo en esa pantalla y lo apunta en el registro; vuelve a salir si cambia el nivel o el motivo. No se envía a la API.

## Qué falta (para Roberto)

1. **La API todavía no evalúa.** `api/main.py` guarda y reenvía telemetría, eventos y chequeos, pero no llama a `risk.evaluate()`: la evaluación ③ solo llega si alguien hace `POST /api/v1/assessment`. Hasta entonces, sistemas, tendencias y acciones salen en gris (*No data*). Además importa `contracts.schemas`, que aún no está en el repositorio.
2. **Tripulantes.** No hay endpoint con la lista: la consola pide a la API los de `KNOWN_CREW` en `js/app.js` (los mismos que `crew_names` en `api/main.py`) y añade sola cualquier `crew_id` nuevo que llegue por el WebSocket.
3. **Chequeo diario.** Falta validar rangos y hacerlo guiado, paso a paso.
4. **Gráficas.** Falta el histórico de 7 días con las medidas reales: el motor solo manda la recta.
5. **Registro y reconocimientos.** Ahora viven solo en la memoria de la página: al recargar se pierden. Si el equipo los quiere guardar, hace falta un endpoint.
6. **Cuerpo.** `hologram.js` es un boceto hecho con cilindros redondeados (cápsulas) de puntos. Se puede cambiar por un SVG o un modelo real sin tocar `app.js` si se mantienen `setLevels`, `setFocus`, `setBpm` y `onPick`.

Los textos de la página y de los datos de ejemplo son inventados, salvo los nombres de campos, que salen de `contracts/`.
