// 10k NTC thermistor test (body temperature)
// No libraries needed. Serial Monitor at 115200 baud.
//
// Wiring:
//   5V -> thermistor -> A0 -> 10k resistor -> GND
//   (the thermistor has no polarity)

const byte  PIN_NTC = A0;
const float R_FIXED = 10000.0;   // 10k resistor

// Steinhart-Hart coefficients of the kit's thermistor (Elegoo tutorial)
const float SH_A = 0.001129148;
const float SH_B = 0.000234125;
const float SH_C = 0.0000000876741;

// Calibration: put (thermometer temperature) - (measured temperature) here
const float CAL_OFFSET_C = 0.0;

const byte N_SAMPLES = 20;          // average of 20 readings per measurement
const unsigned long PERIOD_MS = 1000;

// Stability: less than 0.2 C variation over the last 30 s
const byte WINDOW_S = 30;
float history[WINDOW_S];
byte idxHist = 0, nHist = 0;

unsigned long lastMs = 0;

float readAdcAverage() {
  long sum = 0;
  for (byte i = 0; i < N_SAMPLES; i++) {
    sum += analogRead(PIN_NTC);
    delay(5);
  }
  return sum / (float)N_SAMPLES;
}

void setup() {
  Serial.begin(115200);
  Serial.println(F("Thermistor test. Hold it between your fingers or in your armpit."));
  Serial.println(F("Wait for it to say STABLE (3-5 min in the armpit)."));
}

void loop() {
  if (millis() - lastMs < PERIOD_MS) return;
  lastMs = millis();

  float adc = readAdcAverage();

  if (adc < 5) {
    Serial.println(F("ERROR: A0 near 0 V. The thermistor is not reaching 5V or is loose."));
    return;
  }
  if (adc > 1018) {
    Serial.println(F("ERROR: A0 near 5 V. The 10k resistor is not reaching GND or is loose."));
    return;
  }

  float rNtc = R_FIXED * (1023.0 / adc - 1.0);
  float lnR  = log(rNtc);
  float tK   = 1.0 / (SH_A + SH_B * lnR + SH_C * lnR * lnR * lnR);
  float tC   = tK - 273.15 + CAL_OFFSET_C;

  history[idxHist] = tC;
  idxHist = (idxHist + 1) % WINDOW_S;
  if (nHist < WINDOW_S) nHist++;

  float mn = tC, mx = tC;
  for (byte i = 0; i < nHist; i++) {
    if (history[i] < mn) mn = history[i];
    if (history[i] > mx) mx = history[i];
  }
  bool stable = (nHist == WINDOW_S) && (mx - mn < 0.2);

  Serial.print(F("ADC: "));
  Serial.print(adc, 1);
  Serial.print(F("   R: "));
  Serial.print(rNtc, 0);
  Serial.print(F(" ohm   Temp: "));
  Serial.print(tC, 1);
  Serial.println(stable ? F(" C   [STABLE]") : F(" C   [stabilizing...]"));

  if (stable) {
    // Same field as in the telemetry JSON of the doc
    Serial.print(F("{\"body_temp_c\":"));
    Serial.print(tC, 1);
    Serial.println(F("}"));
  }
}
