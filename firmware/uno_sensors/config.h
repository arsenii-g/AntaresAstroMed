// AstroMed - Arduino UNO configuration
// Everything that is calibrated or tuned for the demo is here.
#pragma once

// ---------------- Pins ----------------
// D2 free (the PIR is gone)
#define PIN_TILT       3    // tilt switch (to GND, internal pull-up)
#define PIN_DHT        4    // DHT11, DATA
#define PIN_US_TRIG    5    // HC-SR04 TRIG (on the floor, push-ups only)
#define PIN_US_ECHO    6    // HC-SR04 ECHO
#define PIN_BUTTON     7    // optional button: held at power-on = resets met_s (to GND, internal pull-up)
#define PIN_PULSE_LED  8    // red pulse LED (with 220 ohm)
#define PIN_RFID_RST   9    // RC522 RST
#define PIN_RFID_SS    10   // RC522 SDA (SS)   | D11 MOSI, D12 MISO, D13 SCK
#define PIN_NTC        A0   // termistor: 5V -> NTC -> A0 -> 10k -> GND
#define PIN_PULSE_LDR  A1   // pulse photoresistor: 5V -> LDR -> A1 -> 10k -> GND
// A4 = SDA and A5 = SCL of the DS1307 RTC
// D1 (TX) -> 1k/2k divider -> ESP32 GPIO16

#define SERIAL_BAUD          115200
#define TELEMETRY_PERIOD_MS  2000UL
#define DEBUG_SENSORS        1      // 1 = prints one "# dbg ..." line per second (the ESP32 ignores it)

// Partial test: 1 = only RC522 + HC-SR04, with readable messages in the Serial Monitor
// and no telemetry. Set it to 0 once all the sensors are connected.
#define TEST_RFID_US       0

// ---------------- Thermistor (body temperature) ----------------
// Same Steinhart-Hart coefficients as thermistor_test.ino
#define NTC_R_FIXED      10000.0
#define NTC_SH_A         0.001129148
#define NTC_SH_B         0.000234125
#define NTC_SH_C         0.0000000876741
#define BODY_TEMP_OFFSET_C  0.0     // (clinical thermometer) - (what the thermistor reads)
#define BODY_TEMP_MIN_VALID 30.0    // outside 30..45, null is sent (the backend would reject it with 422)
#define BODY_TEMP_MAX_VALID 45.0

// ---------------- Pulse (LED + photoresistor) ----------------
#define PULSE_SAMPLE_MS   20        // 50 Hz
#define PULSE_WINDOW_MS   10000UL   // 10 s window
#define PULSE_MIN_AMP     1.5       // minimum signal amplitude (ADC counts); check it in "# dbg hr_amp="
#define PULSE_MIN_IBI_MS  300       // 200 beats/min at most
#define HR_QUALITY_MIN    0.4       // below this, heart_rate_bpm = null

// ---------------- HC-SR04 (push-ups) ----------------
#define US_TIMEOUT_US     7000UL    // ~1.2 m at most
#define PUSHUP_SAMPLE_MS  50        // 20 Hz
#define PUSHUP_DOWN_CM    15.0      // chest below this = down
#define PUSHUP_UP_CM      28.0      // chest above this = up (counts the rep)
#define PUSHUP_END_MS     10000UL   // summary 10 s after the last push-up

// ---------------- Motion ----------------
#define MOVING_WINDOW_MS        3000UL  // "moving" if there was motion in the last 3 s
#define INACTIVITY_THRESHOLD_S  30      // 600 in real use, 30 in the demo

// ---------------- Alert thresholds (demo, not clinical) ----------------
#define ALERT_HR_HIGH          120
#define ALERT_HR_LOW           45
#define ALERT_BODY_TEMP_HIGH   38.0
#define ALERT_BODY_TEMP_LOW    35.5
#define ALERT_CABIN_TEMP_HIGH  28.0
#define ALERT_CABIN_TEMP_LOW   18.0
#define ALERT_HEAT_INDEX_HIGH  32.0
