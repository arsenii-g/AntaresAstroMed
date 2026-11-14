# Consola AstroMed: frontend conectado a la API

Parte de la consola que Roberto conectó en el commit `06d933e`, conservando su
portada, cuerpo, gráficos y estilo. Esta es la interfaz de esta integración.
Tiene dos páginas: portada (`index.html`) y consola (`console.html`), a la que se
entra con *Open the console*. Es HTML, CSS y JavaScript sin dependencias ni compilación.
Las fuentes usan alternativas del sistema si no hay Internet.

## Cómo verlo

Desde la raíz del repositorio, con las dependencias de Python instaladas:

```bash
python -m uvicorn api.main:app --env-file .env.example --host 0.0.0.0 --port 8000
```

Abrir <http://localhost:8000/console.html>. La API sirve también la web en el mismo
origen y puerto. La puesta en marcha en Windows/macOS/Linux está en el README raíz.
También se puede mantener un servidor separado en 5173:

```bash
python -m http.server 5173 --directory frontend/boceto
```

En 5173 la consola busca por defecto la API en el mismo ordenador, puerto 8000.
Si está en otra máquina: `console.html?api=http://IP:8000`. Admite `&crew=F3786E09`
para seleccionar un perfil al abrir. Los GET y el chequeo no necesitan API key.

Usa `/api/v1/crew` para descubrir perfiles y `/api/v1/crew/active` para recuperar
el fichaje activo al cargar y reconectar. `latest` trae estado, nombre, rol y última
serie; `telemetry`, `checks` y `events` dan el histórico. El WebSocket `/ws` recibe
`telemetry`, `event` y `assessment`. `POST /api/v1/checks` genera una evaluación nueva.
Si cae el enlace, aparece *NO LINK TO BASE* y reconecta a 1, 2, 4… s, hasta 30 s.
Cada 15 s vuelve a consultar el estado para que las medidas antiguas caduquen.

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

- **Datos viejos** (`STALE_S = 15`): se usa la hora de la medida, también en reintentos.
  Después de 15 s, las constantes se ponen en gris y el enlace dice *NO SIGNAL*.
- **Sin detalles técnicos en pantalla**: la consola es para la tripulación, así que no enseña endpoints, JSON ni el origen de los datos. Solo dice si llegan lecturas del sensor. Con datos de ejemplo, la pastilla de arriba añade *DEMO*, para que nadie confunda la demo con datos reales.
- **Aviso**: sale para nivel 2 o 3. *Acknowledge* lo oculta solo en esa pantalla y lo apunta en el registro; vuelve a salir si cambia el nivel o el motivo. No se envía a la API.

## Comportamiento de la integración

- **Follow sensor:** sigue los fichajes RFID y recupera el estado al recargar. Al
  seleccionar manualmente un perfil, deja de seguir la tarjeta hasta pulsar el botón.
- **Chequeo:** tres pasos (ánimo, tensión y glucosa), con opción de omitir lo no medido
  y validación de rangos. Al guardar, vuelve al monitor con la evaluación actualizada.
  Cambiar de tripulante vacía el formulario para no atribuirle respuestas del anterior.
- **Gráficas:** las curvas en vivo unen las medidas por su `ts`, deduplican y dejan
  huecos cuando falta señal. Las gráficas de siete días incluyen puntos medidos,
  ajuste, proyección y umbral, sin modificar los niveles que devuelve el motor.
- **Registro:** recupera los eventos guardados por la API. Los reconocimientos y los
  cambios de nivel observados en esta consola siguen siendo locales a esa página.
- **Resumen para Tierra:** solo se muestra el del tripulante seleccionado y se copia.
  No se transmite a un servicio externo ni se afirma que se haya avisado a nadie.

Pruebas de las utilidades de datos, con Node 20 o posterior y sin instalar paquetes:

```bash
node --test frontend/boceto/tests/data.test.js
```

Los textos de la página y de los datos de ejemplo son inventados, salvo los nombres de campos, que salen de `contracts/`.
