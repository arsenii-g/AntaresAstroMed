// SpaceHealth - configuracion del Arduino UNO
// Todo lo que se calibra o se ajusta para la demo esta aqui.
#pragma once

// ---------------- Pines ----------------
// D2 libre (ya no hay PIR)
#define PIN_TILT       3    // interruptor de inclinacion (a GND, pull-up interno)
#define PIN_DHT        4    // DHT11, DATA
#define PIN_US_TRIG    5    // HC-SR04 TRIG (en el suelo, solo flexiones)
#define PIN_US_ECHO    6    // HC-SR04 ECHO
#define PIN_BUTTON     7    // pulsador opcional: pulsado al encender = reinicia met_s (a GND, pull-up interno)
#define PIN_PULSE_LED  8    // LED rojo del pulso (con 220 ohm)
#define PIN_RFID_RST   9    // RC522 RST
#define PIN_RFID_SS    10   // RC522 SDA (SS)   | D11 MOSI, D12 MISO, D13 SCK
#define PIN_NTC        A0   // termistor: 5V -> NTC -> A0 -> 10k -> GND
#define PIN_PULSE_LDR  A1   // fotorresistencia del pulso: 5V -> LDR -> A1 -> 10k -> GND
// A4 = SDA y A5 = SCL del RTC DS1307
// D1 (TX) -> divisor 1k/2k -> GPIO16 del ESP32

#define SERIAL_BAUD          115200
#define TELEMETRY_PERIOD_MS  5000UL
#define DEBUG_SENSORS        1      // 1 = imprime una linea "# dbg ..." por segundo (el ESP32 la ignora)

// Prueba por partes: 1 = solo RC522 + HC-SR04, con mensajes legibles en el Monitor serie
// y sin telemetria. Ponlo a 0 cuando esten todos los sensores conectados.
#define PRUEBA_RFID_US       0

// ---------------- Termistor (temperatura corporal) ----------------
// Mismos coeficientes Steinhart-Hart que termistor_test.ino
#define NTC_R_FIXED      10000.0
#define NTC_SH_A         0.001129148
#define NTC_SH_B         0.000234125
#define NTC_SH_C         0.0000000876741
#define BODY_TEMP_OFFSET_C  0.0     // (termometro clinico) - (lo que mide el termistor)
#define BODY_TEMP_MIN_VALID 30.0    // fuera de 30..45 se manda null (el backend lo rechazaria con 422)
#define BODY_TEMP_MAX_VALID 45.0

// ---------------- Pulso (LED + fotorresistencia) ----------------
#define PULSE_SAMPLE_MS   20        // 50 Hz
#define PULSE_WINDOW_MS   10000UL   // ventana de 10 s
#define PULSE_MIN_AMP     1.5       // amplitud minima de la senal (cuentas ADC); mirala en "# dbg hr_amp="
#define PULSE_MIN_IBI_MS  300       // 200 lat/min como maximo
#define HR_QUALITY_MIN    0.4       // por debajo, heart_rate_bpm = null

// ---------------- HC-SR04 (flexiones) ----------------
#define US_TIMEOUT_US     7000UL    // ~1,2 m como maximo
#define PUSHUP_SAMPLE_MS  50        // 20 Hz
#define PUSHUP_DOWN_CM    15.0      // pecho por debajo de esto = abajo
#define PUSHUP_UP_CM      28.0      // pecho por encima de esto = arriba (cuenta la repeticion)
#define PUSHUP_END_MS     10000UL   // resumen 10 s despues de la ultima flexion

// ---------------- Movimiento ----------------
#define MOVING_WINDOW_MS        3000UL  // "moving" si hubo movimiento en los ultimos 3 s
#define INACTIVITY_THRESHOLD_S  30      // 600 en real, 30 en la demo

// ---------------- Umbrales de alerta (demo, no clinicos) ----------------
#define ALERT_HR_HIGH          120
#define ALERT_HR_LOW           45
#define ALERT_BODY_TEMP_HIGH   38.0
#define ALERT_BODY_TEMP_LOW    35.5
#define ALERT_CABIN_TEMP_HIGH  28.0
#define ALERT_CABIN_TEMP_LOW   18.0
#define ALERT_HEAT_INDEX_HIGH  32.0
