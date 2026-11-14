# API de AstroMed

La API valida y guarda los mensajes en SQLite, llama al motor Python `risk.evaluate()`
y publica los cambios por `/ws`. Sirve además la portada y la consola que Roberto
ha conectado en `frontend/boceto/`. La puesta en marcha completa está en el README raíz.

## Flujo

1. Validar el JSON con `contracts/schemas.py` y normalizar las fechas a UTC.
2. Guardar el mensaje y su recibo de idempotencia en una misma transacción.
3. Para ese `crew_id`, pasar al motor la telemetría del último minuto y los eventos
   y chequeos de los últimos siete días. Con `crew_id: null`, guardar sin evaluar.
4. Guardar la evaluación y emitir `telemetry` o `event`, seguido de `assessment`.
   Un chequeo emite directamente su nueva evaluación.

Cada mensaje se confirma con `200` y `{"ok": true, "duplicate": false,
"assessment_pending": false}`. Un reintento se confirma con `duplicate: true`,
sin volver a guardar ni difundir el dato. La clave de telemetría es
`(device_id, ts, telemetry)`, la de eventos `(device_id, ts, type)` y la de chequeos
`(crew_id, ts, checks)`. La base de datos garantiza que dos peticiones concurrentes
no creen dos mensajes.

La tabla nueva `ingestion_receipts` convive con las cuatro tablas originales.
También se comprueba la existencia de mensajes anteriores sin recibo: no se borra
ni se reconstruye la base de datos que ya tuviera el equipo.

Si falla el motor, el mensaje recibido sigue guardado y se responde `ok: true` con
`assessment_pending: true`. Se registra la excepción; `/latest` vuelve a intentar
la evaluación y devuelve `assessment: null` y `assessment_error` si continúa fallando.
Un reintento del mismo mensaje también puede recuperar la evaluación pendiente.

## Endpoints

| Método y ruta | Resultado |
|---|---|
| `POST /api/v1/telemetry` | Telemetría del ESP32; requiere `X-API-Key` |
| `POST /api/v1/events` | Eventos de la placa; requiere `X-API-Key` |
| `POST /api/v1/checks` | Chequeo manual; sin API key por decisión del equipo |
| `GET /api/v1/crew` | Lista de tarjetas conocidas y desconocidas guardadas, con nombre, rol y `assigned` |
| `GET /api/v1/crew/active` | Último fichaje RFID (`in` → ese tripulante, `out` → nadie); sin fichajes, el de la última telemetría. Con varias placas a la vez, la telemetría alternaría de tripulante cada 2 s |
| `GET /api/v1/crew/{id}/latest` | Metadatos, última telemetría, evaluación recalculada a la hora actual y última serie de ejercicio |
| `GET /api/v1/crew/{id}/telemetry?from=&to=&limit=` | Últimas lecturas del intervalo, devueltas cronológicamente |
| `GET /api/v1/crew/{id}/checks?from=&to=&limit=` | Chequeos del intervalo para dibujar las medidas reales |
| `GET /api/v1/events?crew_id=&type=&from=&to=&limit=` | Eventos filtrables, en orden cronológico |
| `GET /api/v1/status` | Estado del backend, hora y modo demo |
| `WS /ws` | Sobres `{"type": "telemetry" / "event" / "assessment", "data": {...}}` |
| `GET /` y `GET /console.html` | Portada y consola; ambas incluyen cabecera HTTP `Date` |

`from` y `to` son fechas ISO 8601 con zona horaria. El límite máximo es 10.000.
Por defecto se devuelven las últimas 3.000 telemetrías o 1.000 eventos/chequeos;
la consola pide las 48 telemetrías más recientes y siete días de chequeos/eventos.

`POST /api/v1/assessment` se conserva como ruta antigua de importación con API key,
marcada como obsoleta en `/docs`. El funcionamiento normal no depende de ella.

## Validación y compatibilidad

- Los datos ausentes son `null`, nunca cero ni verde. Se admite la pérdida completa
  del DHT11 y la ausencia de tripulante.
- Los números admiten enteros o decimales integrales cuando corresponde. Se rechazan
  booleanos, números no finitos y fechas sin zona horaria.
- Se aceptan campos adicionales y tarjetas desconocidas. Los eventos futuros de tipo
  desconocido se guardan como eventos opacos, conservando sus datos.
- Los rangos imposibles se rechazan con `422`, como pide la guía. El motivo se guarda
  en `rejected_messages`. Un JSON roto recibe `400`; una clave ausente o incorrecta,
  `401`; un error temporal de SQLite, `503`, para permitir el reintento.
- Se preserva `sqlite:///./spacehealth.db` y los nombres de variables `SPACEHEALTH_*`
  para usar la configuración existente. El nombre público es AstroMed.
- Un navegador lento no bloquea indefinidamente el acuse de recibo de la placa.

Los perfiles de las tarjetas del kit (`F3786E09` y `336F8312`) se editan en
`api/crew.py`; una tarjeta nueva se marca como sin asignar.
