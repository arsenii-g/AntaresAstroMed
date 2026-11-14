# frontend/boceto/: boceto visual de ArgosMed

Boceto visual de ArgosMed, para que Roberto lo use de referencia y lo complete. Su app en Vue está en la rama `web/body-svg`; este boceto va en su propia carpeta para no chocar con ella. Tiene dos páginas: una portada (`index.html`) y la consola de operaciones (`console.html`), a la que se entra con *Open the console*. Es HTML, CSS y JavaScript sin dependencias ni paso de compilación: funciona sin internet (solo las fuentes vienen de Google Fonts, y si no cargan se usan las del sistema).

## Cómo verlo

Los módulos de JavaScript no cargan abriendo el archivo con doble clic; hace falta un servidor local:

```bash
python3 -m http.server 5173 --directory frontend/boceto
```

Y abrir <http://localhost:5173>. Sale con **datos de ejemplo** (`js/mock.js`): cada tripulante pasa por tres estados, uno cada 7 s. El segundo tripulante llega a nivel 3: salta el aviso arriba y aparece el resumen para Tierra.

## Qué hay

| Archivo | Qué es |
|---|---|
| `index.html` | Portada: planeta, explicación en tres pasos y botón a la consola |
| `landing.css`, `js/landing.js` | Estilo y animaciones de la portada |
| `console.html` | Consola, con dos vistas. **Monitor**: tripulación, sistemas, cuerpo, constantes, tendencia, acciones, resumen para Tierra, registro de eventos y enlace con el vehículo. **Daily check**: el formulario del contrato ② |
| `styles.css` | Estilo de la consola. Colores, fuentes y niveles son variables al principio |
| `js/app.js` | Recibe mensajes `{ type, data }` y pinta. También lleva el registro de eventos (cambios de nivel por sistema), el aviso con botón *Acknowledge* y la antigüedad de los datos |
| `js/mock.js` | Datos de ejemplo con la forma de los contratos ① y ③ |
| `js/hologram.js` | Cuerpo 3D de puntos, coloreado por sistema; se puede hacer clic y girar |
| `js/planet.js` | Planeta 3D: fondo de la portada y panel *Vehicle link* de la consola (cambia con sus opciones) |
| `js/stage.js` | Bucle de dibujo común a los dos lienzos |

Los niveles se pintan con el atributo `data-level` (`0` verde, `1` ámbar, `2` naranja, `3` rojo, vacío = gris "No data"). Un nivel `null` nunca se pinta en verde.

Decisiones de criterio propio, ajustables en `js/app.js`:

- **Datos viejos** (`STALE_S = 15`): si no llega telemetría en 15 s (3 mensajes de la placa), las constantes se ponen en gris y el enlace dice *NO SIGNAL*.
- **Sin detalles técnicos en pantalla**: la consola es para la tripulación, así que no enseña endpoints, JSON ni el origen de los datos. Solo dice si llegan lecturas del sensor. Con datos de ejemplo, la pastilla de arriba añade *DEMO*, para que nadie confunda la demo con datos reales.
- **Aviso**: sale para nivel 2 o 3. *Acknowledge* lo oculta solo en esa pantalla y lo apunta en el registro; vuelve a salir si cambia el nivel o el motivo. No se envía a la API.

## Qué falta (para Roberto)

1. **Conectar la API.** En `js/app.js`, poner `API_URL` (por ejemplo `"http://localhost:8000"`). La página abre un WebSocket y espera mensajes como `contracts/ws-message.example.json`. Falta acordar con Jesus:
   - la ruta del WebSocket (ahora `WS_PATH = "/ws"`, inventada);
   - si la telemetría también llega por WebSocket con `type: "telemetry"`. Las casillas de pulso, temperatura y cabina la necesitan; la evaluación ③ solo trae los motivos, no los valores;
   - pedir el último estado al cargar con `GET /api/v1/crew/{crew_id}/latest`.
2. **Tripulantes.** Nombre y rol están escritos a mano en `js/mock.js` (`CREW`). Deberían venir de la API.
3. **Chequeo diario.** El formulario ya construye el JSON del contrato ② (no se enseña en pantalla; en modo demo sale en la consola del navegador). Con `API_URL` puesto lo envía a `POST /api/v1/checks` con la cabecera `X-API-Key`. Falta validar rangos y hacerlo guiado, paso a paso.
4. **Gráficas.** Solo hay una línea con los últimos pulsos y una barra por tendencia. Falta la gráfica de 7 días por indicador.
5. **Registro y reconocimientos.** Ahora viven solo en la memoria de la página: al recargar se pierden. Si el equipo los quiere guardar, hace falta un endpoint.
6. **Cuerpo.** `hologram.js` es un boceto hecho con elipsoides. Se puede cambiar por un SVG o un modelo real sin tocar `app.js` si se mantienen `setLevels`, `setFocus`, `setBpm` y `onPick`.

Los textos de la página y de los datos de ejemplo son inventados, salvo los nombres de campos, que salen de `contracts/`.
