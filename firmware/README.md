# AstroMed · Team Antares: firmware y conexiones

Sigue [AstroMed: formato JSON para el backend](FORMATO_JSON_BACKEND.md), sin el sueño, la respiración ni el PIR. El HC-SR04 solo cuenta flexiones, y `resp_rate_bpm` va siempre a `null` para no cambiar el formato del JSON.

| Carpeta | Placa | Qué hace |
| --- | --- | --- |
| `uno_sensores/` | Arduino UNO | lee los sensores y manda una línea JSON por mensaje por el TX (D1) |
| `esp32_gateway/` | ESP32 Dev Module | recibe esas líneas, les pone `device_id` y `ts`, y las manda por POST al backend con cola de 50 y reintentos |
| `mock_backend.py` | PC | backend de prueba que imprime lo que llega |
| `pruebas/prueba_sensores/` | Arduino UNO | comprueba que todos los sensores están conectados y funcionan |
| `pruebas/rfid_test/`, `pruebas/termistor_test/` | Arduino UNO | pruebas sueltas del RC522 y del termistor |
| `FORMATO_JSON_BACKEND.md` | — | formato final del JSON para el backend (de aquí salen los `contracts/`) |

## Librerías

- **UNO:** solo `MFRC522` (GithubCommunity), que ya está instalada. El DHT11 y el DS1307 se leen sin librería.
- **ESP32:** placa «esp32» de Espressif en el Gestor de placas, y la librería `ArduinoJson` 7 de Benoit Blanchon.

## Conexiones del Arduino UNO

Lleva todos los GND a la línea negativa de la protoboard, y los 5 V a la positiva.

| Componente | Pin del componente | Va a |
| --- | --- | --- |
| **RC522 (RFID)** | SDA | D10 |
| | SCK | D13 |
| | MOSI | D11 |
| | MISO | D12 |
| | IRQ | sin conectar |
| | GND | GND |
| | RST | D9 |
| | 3.3V | **3.3V (nunca a 5 V)** |
| **HC-SR04** | VCC | 5V |
| | TRIG | D5 |
| | ECHO | D6 |
| | GND | GND |
| **Interruptor de inclinación** (lo lleva el tripulante; es el único sensor de movimiento) | una pata | D3 |
| | otra pata | GND (sin resistencia: se usa el pull-up interno) |
| **Pulsador (opcional)** | una pata | D7 |
| | pata opuesta | GND (sin resistencia: se usa el pull-up interno) |
| **DHT11** (módulo de 3 pines) | VCC (+) | 5V |
| | DATA (S) | D4 |
| | GND (−) | GND |
| **RTC DS1307** | VCC | 5V |
| | GND | GND |
| | SDA | A4 |
| | SCL | A5 |
| **Termistor NTC 10k** | una pata | 5V |
| | otra pata | A0, y de A0 una resistencia de 10 kΩ a GND |
| **LED rojo del pulso** | pata larga (+) | resistencia de 220 Ω → D8 |
| | pata corta (−) | GND |
| **Fotorresistencia del pulso** | una pata | 5V |
| | otra pata | A1, y de A1 una resistencia de 10 kΩ a GND |

Si tu DHT11 es el sensor suelto de 4 patas (sin placa), pon una resistencia de 10 kΩ entre DATA y 5V.

### Pulso: montaje

El LED y la fotorresistencia van enfrentados, con el dedo en medio: el LED ilumina la yema por un lado y la fotorresistencia recoge la luz por el otro. Tápalo con cinta negra o un tubo para que no entre luz de la sala, y no aprietes el dedo.

## UNO → ESP32

Solo hacen falta dos cables y un divisor de tensión, porque el TX del UNO da 5 V y el ESP32 aguanta 3,3 V.

| Desde | Pasa por | Llega a |
| --- | --- | --- |
| UNO D1 (TX) | resistencia de 1 kΩ | punto intermedio |
| punto intermedio | — | ESP32 GPIO16 (RX2) |
| punto intermedio | resistencia de 2 kΩ (o 2,2 kΩ) | GND |
| UNO GND | — | ESP32 GND (**obligatorio**, GND común) |

- No conectes el TX del ESP32 al UNO: no hace falta, y así se puede subir el sketch al UNO sin desconectar nada.
- Si no tienes una de 2 kΩ, pon dos de 1 kΩ en serie.
- Alimenta cada placa por su USB.

## Puesta en marcha

1. Sube `uno_sensores` al UNO (placa «Arduino Uno»). En el Monitor serie, a 115200, verás las líneas `{"t":"tel",...}` cada 2 s y una línea `# dbg ...` por segundo.
2. Copia `esp32_gateway/config.example.h` como `esp32_gateway/config.h` y rellena el WiFi (**solo 2,4 GHz**), `API_BASE`, `API_KEY` y `DEVICE_ID`. `config.h` no se sube a git porque lleva claves.
3. Sube `esp32_gateway` al ESP32 (placa «ESP32 Dev Module»). En su Monitor serie verás `[wifi]`, `[envio]` y `[estado]`.
4. Si el backend aún no está, arranca `python3 mock_backend.py` en el PC y apunta `API_BASE` a la IP del PC.

## Uso

- **Pasar tarjeta:** empieza a medir a ese tripulante (`crew_checkin` con `in`). La misma tarjeta otra vez lo saca (`out`). Otra tarjeta saca al anterior y mete al nuevo.
- **Pulsador al encender el UNO:** reinicia el tiempo de misión (`met_s` = 0). El inicio de misión se guarda en el DS1307, así que sobrevive a los reinicios. Es lo único que hace el pulsador.
- **Flexiones:** HC-SR04 en el suelo mirando hacia arriba, bajo el pecho. El resumen sale 10 s después de la última.
- **Prueba por partes:** con `PRUEBA_RFID_US` a `1` en `config.h` solo funcionan el RC522 y el HC-SR04, y cada segundo sale una línea legible con la distancia, `arriba`/`ABAJO` y las repeticiones. Ponlo a `0` cuando estén todos los sensores.

## Comprobar las conexiones

Sube `pruebas/prueba_sensores` al UNO y abre el Monitor serie a 115200. Primero hace pruebas automáticas (RTC, RC522, DHT11, termistor, LED + fotorresistencia y HC-SR04), cada una con `[ OK ]`, `[AVISO]` o `[FALLO]` y qué revisar. Después pide pasar una tarjeta, inclinar el interruptor, pulsar el pulsador, mover la mano ante el HC-SR04, apretar el termistor y poner el dedo en el pulso, y los va tachando. Envía `r` para repetir las automáticas.

## Si el ESP32 no llega al backend

El Monitor serie del ESP32 (115200) dice dónde está el fallo:

| Mensaje | Qué pasa | Qué hacer |
| --- | --- | --- |
| `[wifi] ... NO_AP_FOUND` | no ve la red | el ESP32 solo usa **2,4 GHz**: pon el punto de acceso en 2,4 GHz y revisa el nombre |
| `[wifi] ... AUTH_FAIL` o `HANDSHAKE_TIMEOUT` | ve la red pero no entra | revisa la contraseña |
| `[diag] ... falla al instante` | el ordenador contesta, pero no hay servidor en ese puerto | arranca la API con `--host 0.0.0.0` (no `127.0.0.1`) |
| `[diag] ... se agota el tiempo` | los paquetes no llegan | cortafuegos del ordenador del backend, o un hotspot que aísla a los clientes |
| `[envio] ... fallo (500)` + `cuerpo:` | llega, pero la API da error interno | mira el traceback en la terminal de uvicorn |

Lo que nos pasó en el hackathon, por si se repite:

- **El hotspot de un móvil Xiaomi aísla a los clientes:** el móvil abría la API, pero el ESP32 no. Lo resolvimos con la zona con cobertura de Windows en el portátil del backend (2,4 GHz). La API queda en `http://192.168.137.1:8000`.
- **Windows bloqueaba `python.exe` en redes públicas.** Las reglas de bloqueo ganan a las de permitir, así que abrir el puerto 8000 no bastaba. En PowerShell como administrador:
  ```
  Get-NetFirewallRule -Direction Inbound -Action Block -Enabled True | Where-Object { $_.DisplayName -eq "python.exe" } | Disable-NetFirewallRule
  New-NetFirewallRule -DisplayName "AstroMed API 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Any
  ```

## Calibración (con `# dbg` en el Monitor serie del UNO)

Todos los valores están en `uno_sensores/config.h`.

| Qué | Cómo |
| --- | --- |
| Temperatura corporal | Compara con un termómetro y pon la diferencia en `BODY_TEMP_OFFSET_C`. Fuera de 30–45 °C se manda `null`, porque el backend rechazaría el mensaje entero. |
| Pulso | Mira `hr_amp=` con el dedo puesto. Si no llega a 1,5, baja `PULSE_MIN_AMP`; si cuenta latidos sin dedo, súbelo. |
| Flexiones | Mira `dist_cm=` arriba y abajo y ajusta `PUSHUP_DOWN_CM` y `PUSHUP_UP_CM`. |
| Inactividad | `INACTIVITY_THRESHOLD_S` vale 30 para la demo (600 en real). |

## Detalles que conviene saber

- Lo que no se puede medir va como `null`, también los campos de cabina si el DHT11 falla 5 veces seguidas.
- El `ts` lo pone el ESP32 al recibir el mensaje y no cambia en los reintentos, así el backend puede descartar duplicados. Si dos eventos del mismo tipo caen en el mismo segundo (el `out` y el `in` al cambiar de tarjeta), el segundo se adelanta 1 s.
- Sin Internet para NTP, el ESP32 toma la hora de la cabecera `Date` del backend. Hasta tener hora no envía, pero guarda los mensajes en la cola.
- Si el backend responde 4xx (por ejemplo, 422 o 401), el mensaje se descarta y se imprime el motivo, porque reintentar no lo arreglaría. Con 5xx o sin respuesta, reintenta.
