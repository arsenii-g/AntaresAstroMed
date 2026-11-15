# AstroMed · Team Antares: simulador de dos ESP32

Simula **dos placas ESP32, una por tripulante**, que mandan a la API lo mismo que la placa real: mismo JSON, cada 2 s, con la misma cola y los mismos reintentos. La API guarda los mensajes, llama al motor de riesgos y avisa a la web por WebSocket. Nada se calcula en el simulador ni en la web: los niveles, los motivos y las rectas salen del motor.

El **chequeo manual** (tensión, glucosa y ánimo) no se simula. Se mete a mano en la pestaña *Daily check*. Hasta el primer chequeo, el sistema neuro sale *No data*.

## Puesta en marcha

1. Arranca la API desde la raíz del repositorio (ver el README raíz):

   ```bash
   python -m uvicorn api.main:app --env-file .env.example --host 0.0.0.0 --port 8000
   ```

2. En otra terminal, también desde la raíz:

   ```bash
   python -m simulator.simulate
   ```

3. Abre <http://localhost:8000/console.html>.

Para grabar desde cero sin perder datos anteriores, configura en `.env` una ruta nueva, por ejemplo `ASTROMED_DATABASE_URL=sqlite:///./astromed-recording.db`, y arranca la API con `--env-file .env`. Sin una URL explícita, la API reutiliza `spacehealth.db` si ya existe y crea `astromed.db` en instalaciones nuevas. Los chequeos y las series de los últimos 7 días se conservan entre ejecuciones.

`Ctrl+C` para el simulador y manda el `crew_checkin` de salida de los dos tripulantes.

## `config.json`

```json
{
  "api_url": "http://localhost:8000",
  "api_key": "spacehealth-dev-key-2026",
  "mode": "fixed",
  "interval_s": 2,
  "pushup_every_s": 20,
  "crew": [
    { "crew_id": "F3786E09", "device_id": "esp32-sim-1", "level": 0 },
    { "crew_id": "336F8312", "device_id": "esp32-sim-2", "level": 2 }
  ]
}
```

| Campo | Qué hace |
|---|---|
| `api_url`, `api_key` | Dónde manda y con qué `X-API-Key`. La clave tiene que ser la de la API (`ASTROMED_API_KEY`) |
| `mode` | `"fixed"`: cada tripulante se queda en su nivel. `"normal"`: el nivel de cada sistema va cambiando solo |
| `interval_s` | Cada cuánto se manda telemetría (la placa real: 2 s) |
| `pushup_every_s` | Cada cuánto hace una serie de flexiones |
| `crew[].level` | Nivel 0, 1, 2 o 3 para todo, o uno por sistema: `{"cardiovascular": 3, "musculoskeletal": 0, "environment": 1}` |
| `normal` | Ajustes del modo normal (abajo) |

El orden de `crew` importa: la web sigue la última tarjeta que fichó, que es la del último de la lista.

Sin tocar el archivo:

```bash
python -m simulator.simulate --level F3786E09=1 --level 336F8312=3
python -m simulator.simulate --mode normal
python -m simulator.simulate --url http://192.168.137.1:8000
```

## Qué manda en cada nivel (modo `fixed`)

Los valores están en el centro de cada franja de `risk/thresholds.json`, con algo de ruido, para que el ruido no cambie el nivel.

| Sistema | Nivel 0 | Nivel 1 | Nivel 2 | Nivel 3 |
|---|---|---|---|---|
| Cardiovascular | pulso 72, 36,7 °C | pulso 108, 37,7 °C | pulso 114, **38,6 °C** | **pulso 160**, 39,8 °C |
| Musculoesquelético: caída de flexiones frente a su media | 0 % | 15 % | 30 % | 50 % |
| Entorno: cabina | 22,5 °C, 45 % | 26 °C, 52 % | 29 °C, 55 % | 33,5 °C, 50 % |
| Neuro | solo con el chequeo manual | | | |

- **Nivel 2 cardiovascular por la fiebre, no por el pulso:** el motor rebaja a ámbar un pulso naranja durante 5 minutos tras unas flexiones, y el simulador las hace cada 20 s.
- **Naranja y rojo tardan unos 10 s:** el motor pide lecturas sostenidas (3 lecturas y 10 s). Mientras tanto sale ámbar.
- **Flexiones:** las 3 primeras series son las de siempre (20) y forman su basal. Desde la cuarta, cada serie cae el porcentaje del nivel frente a la media de las anteriores, que es lo que mide el motor. En los niveles 2 y 3 las repeticiones van bajando con el tiempo, porque la media también baja.
- **Inactividad:** el tripulante se mueve cada 12 s, así que nunca llega a los 30 s del aviso.
- **Si la API ya tiene series de ese tripulante** (de una ejecución anterior), el simulador las lee al arrancar y las usa como basal, igual que el motor.

## Modo `normal`

Cada sistema elige un nivel nuevo cada 40 a 90 s (40 % verde, 30 % ámbar, 20 % naranja, 10 % rojo) y va hacia él en rampa, a 20 s por nivel. Las rampas son las que detectan las rectas de los sensores: "Heart rate reaches 120 bpm in 14 s".

```json
"normal": { "seed": 1, "change_every_s": [40, 90], "ramp_s_per_level": 20, "level_weights": [0.4, 0.3, 0.2, 0.1] }
```

Con la misma `seed` sale siempre la misma secuencia. Cámbiala para otra.

## Sin API

```bash
python -m simulator.simulate --print --count 3                  # el JSON que mandaría
python -m simulator.simulate --evaluate --fast --count 120      # niveles del motor, en local
```

## Pruebas

```bash
python -m pytest -q simulator
```
