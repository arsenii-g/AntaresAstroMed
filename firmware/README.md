# AstroMed · Team Antares: firmware and wiring

It follows [AstroMed: JSON format for the backend](BACKEND_JSON_FORMAT.md), with no sleep, breathing or PIR measurement. The HC-SR04 only counts push-ups, and `resp_rate_bpm` is always `null` so the JSON format does not change.

| Folder | Board | What it does |
| --- | --- | --- |
| `uno_sensors/` | Arduino UNO | reads the sensors and sends one JSON line per message on TX (D1) |
| `esp32_gateway/` | ESP32 Dev Module | receives those lines, adds `device_id` and `ts`, and POSTs them to the backend with a 50-message queue and retries |
| `mock_backend.py` | PC | test backend that prints what arrives |
| `tests/sensor_test/` | Arduino UNO | checks that all the sensors are connected and working |
| `tests/rfid_test/`, `tests/thermistor_test/` | Arduino UNO | standalone tests of the RC522 and the thermistor |
| `BACKEND_JSON_FORMAT.md` | — | final JSON format for the backend (the `contracts/` come from here) |

## Libraries

- **UNO:** only `MFRC522` (GithubCommunity). The DHT11 and the DS1307 are read without a library.
- **ESP32:** the "esp32" board package by Espressif in the Boards Manager, and the `ArduinoJson` 7 library by Benoit Blanchon.

## Arduino UNO wiring

Run all GND wires to the breadboard's negative rail, and all 5 V wires to the positive rail.

| Component | Component pin | Goes to |
| --- | --- | --- |
| **RC522 (RFID)** | SDA | D10 |
| | SCK | D13 |
| | MOSI | D11 |
| | MISO | D12 |
| | IRQ | not connected |
| | GND | GND |
| | RST | D9 |
| | 3.3V | **3.3V (never to 5 V)** |
| **HC-SR04** | VCC | 5V |
| | TRIG | D5 |
| | ECHO | D6 |
| | GND | GND |
| **Tilt switch** (worn by the crew member; it is the only motion sensor) | one leg | D3 |
| | other leg | GND (no resistor: the internal pull-up is used) |
| **Push button (optional)** | one leg | D7 |
| | opposite leg | GND (no resistor: the internal pull-up is used) |
| **DHT11** (3-pin module) | VCC (+) | 5V |
| | DATA (S) | D4 |
| | GND (−) | GND |
| **RTC DS1307** | VCC | 5V |
| | GND | GND |
| | SDA | A4 |
| | SCL | A5 |
| **10k NTC thermistor** | one leg | 5V |
| | other leg | A0, and from A0 a 10 kΩ resistor to GND |
| **Red pulse LED** | long leg (+) | 220 Ω resistor → D8 |
| | short leg (−) | GND |
| **Pulse photoresistor** | one leg | 5V |
| | other leg | A1, and from A1 a 10 kΩ resistor to GND |

If your DHT11 is the loose 4-pin sensor (no breakout board), put a 10 kΩ resistor between DATA and 5V.

### Pulse: assembly

The LED and the photoresistor face each other with the finger in between: the LED lights the fingertip from one side and the photoresistor picks up the light on the other. Cover it with black tape or a tube so room light does not get in, and do not squeeze the finger.

## UNO → ESP32

Only two wires and a voltage divider are needed, because the UNO TX outputs 5 V and the ESP32 tolerates 3.3 V.

| From | Through | To |
| --- | --- | --- |
| UNO D1 (TX) | 1 kΩ resistor | midpoint |
| midpoint | — | ESP32 GPIO16 (RX2) |
| midpoint | 2 kΩ resistor (or 2.2 kΩ) | GND |
| UNO GND | — | ESP32 GND (**required**, common GND) |

- Do not connect the ESP32 TX to the UNO: it is not needed, and this way you can upload the sketch to the UNO without disconnecting anything.
- If you do not have a 2 kΩ resistor, use two 1 kΩ resistors in series.
- Power each board from its own USB.

## Getting started

1. Upload `uno_sensors` to the UNO (board "Arduino Uno"). In the Serial Monitor at 115200 you will see `{"t":"tel",...}` lines every 2 s and one `# dbg ...` line per second.
2. Copy `esp32_gateway/config.example.h` as `esp32_gateway/config.h` and fill in the WiFi (**2.4 GHz only**), `API_BASE`, `API_KEY` and `DEVICE_ID`. `config.h` is not committed to git because it holds keys.
3. Upload `esp32_gateway` to the ESP32 (board "ESP32 Dev Module"). In its Serial Monitor you will see `[wifi]`, `[send]` and `[status]`.
4. If the backend is not up yet, run `python3 mock_backend.py` on the PC and point `API_BASE` at the PC's IP.

## Usage

- **Scan a card:** starts measuring that crew member (`crew_checkin` with `in`). The same card again checks them out (`out`). A different card checks out the previous one and checks in the new one.
- **Button held at UNO power-on:** resets the mission time (`met_s` = 0). The mission start is stored in the DS1307, so it survives restarts. This is all the button does.
- **Push-ups:** HC-SR04 on the floor facing up, under the chest. The summary is sent 10 s after the last one.
- **Partial test:** with `TEST_RFID_US` set to `1` in `config.h`, only the RC522 and the HC-SR04 work, and every second a readable line is printed with the distance, `up`/`DOWN` and the reps. Set it back to `0` once all the sensors are connected.

## Checking the wiring

Upload `tests/sensor_test` to the UNO and open the Serial Monitor at 115200. It first runs automatic tests (RTC, RC522, DHT11, thermistor, LED + photoresistor and HC-SR04), each one with `[ OK ]`, `[WARN]` or `[FAIL]` and what to check. Then it asks you to scan a card, tilt the switch, press the button, move your hand in front of the HC-SR04, squeeze the thermistor and put your finger on the pulse sensor, and checks them off. Send `r` to repeat the automatic tests.

## If the ESP32 cannot reach the backend

The ESP32 Serial Monitor (115200) shows where the problem is:

| Message | What is happening | What to do |
| --- | --- | --- |
| `[wifi] ... NO_AP_FOUND` | cannot see the network | the ESP32 only uses **2.4 GHz**: set the access point to 2.4 GHz and check the name |
| `[wifi] ... AUTH_FAIL` or `HANDSHAKE_TIMEOUT` | sees the network but cannot join | check the password |
| `[diag] ... Fails instantly` | the computer answers, but no server is on that port | start the API with `--host 0.0.0.0` (not `127.0.0.1`) |
| `[diag] ... Times out` | packets are not arriving | firewall on the backend computer, or a hotspot that isolates clients |
| `[send] ... failed (500)` + `body:` | it arrives, but the API returns an internal error | check the traceback in the uvicorn terminal |

What happened to us at the hackathon, in case it happens again:

- **A Xiaomi phone hotspot isolates clients:** the phone could open the API, but the ESP32 could not. We fixed it with the Windows mobile hotspot on the backend laptop (2.4 GHz). The API is then at `http://192.168.137.1:8000`.
- **Windows was blocking `python.exe` on public networks.** Block rules win over allow rules, so opening port 8000 was not enough. In PowerShell as administrator:
  ```
  Get-NetFirewallRule -Direction Inbound -Action Block -Enabled True | Where-Object { $_.DisplayName -eq "python.exe" } | Disable-NetFirewallRule
  New-NetFirewallRule -DisplayName "AstroMed API 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Any
  ```

## Calibration (using `# dbg` in the UNO Serial Monitor)

All the values are in `uno_sensors/config.h`.

| What | How |
| --- | --- |
| Body temperature | Compare with a thermometer and put the difference in `BODY_TEMP_OFFSET_C`. Outside 30–45 °C, `null` is sent, because the backend would reject the whole message. |
| Pulse | Watch `hr_amp=` with the finger in place. If it does not reach 1.5, lower `PULSE_MIN_AMP`; if it counts beats with no finger, raise it. |
| Push-ups | Watch `dist_cm=` at the top and bottom and adjust `PUSHUP_DOWN_CM` and `PUSHUP_UP_CM`. |
| Inactivity | `INACTIVITY_THRESHOLD_S` is 30 for the demo (600 in real use). |

## Good to know

- Anything that cannot be measured goes as `null`, including the cabin fields if the DHT11 fails 5 times in a row.
- The `ts` is set by the ESP32 when it receives the message and does not change on retries, so the backend can discard duplicates. If two events of the same type fall in the same second (the `out` and the `in` when swapping cards), the second is moved ahead by 1 s.
- With no Internet for NTP, the ESP32 takes the time from the backend's `Date` header. Until it has the time it does not send, but it keeps the messages in the queue.
- If the backend answers 4xx except 401, 403, 408 and 429 (for example, 422), the message is dropped and the reason is printed, because retrying would not fix it. With 401, 403, 408, 429, 5xx or no response, it retries (so a wrong API key does not lose data).
