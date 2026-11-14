// Prueba del termistor NTC 10k (temperatura corporal)
// No necesita librerias. Monitor serie a 115200 baudios.
//
// Conexiones:
//   5V -> termistor -> A0 -> resistencia 10k -> GND
//   (el termistor no tiene polaridad)

const byte  PIN_NTC = A0;
const float R_FIJA = 10000.0;   // resistencia de 10k   // resistencia de 10k

// Coeficientes Steinhart-Hart del termistor del kit (tutorial de Elegoo)
const float SH_A = 0.001129148;
const float SH_B = 0.000234125;
const float SH_C = 0.0000000876741;

// Calibracion: pon aqui (temperatura del termometro) - (temperatura medida)
const float CAL_OFFSET_C = 0.0;

const byte N_MUESTRAS = 20;          // media de 20 lecturas por medida
const unsigned long PERIODO_MS = 1000;

// Estabilidad: menos de 0,2 C de variacion en los ultimos 30 s
const byte VENTANA_S = 30;
float historial[VENTANA_S];
byte idxHist = 0, nHist = 0;

unsigned long ultimaMs = 0;

float leerAdcMedio() {
  long suma = 0;
  for (byte i = 0; i < N_MUESTRAS; i++) {
    suma += analogRead(PIN_NTC);
    delay(5);
  }
  return suma / (float)N_MUESTRAS;
}

void setup() {
  Serial.begin(115200);
  Serial.println(F("Prueba del termistor. Sujetalo entre los dedos o en la axila."));
  Serial.println(F("Espera a que ponga ESTABLE (3-5 min en la axila)."));
}

void loop() {
  if (millis() - ultimaMs < PERIODO_MS) return;
  ultimaMs = millis();

  float adc = leerAdcMedio();

  if (adc < 5) {
    Serial.println(F("ERROR: A0 casi a 0 V. El termistor no llega a 5V o esta suelto."));
    return;
  }
  if (adc > 1018) {
    Serial.println(F("ERROR: A0 casi a 5 V. La resistencia de 10k no llega a GND o esta suelta."));
    return;
  }

  float rNtc = R_FIJA * (1023.0 / adc - 1.0);
  float lnR  = log(rNtc);
  float tK   = 1.0 / (SH_A + SH_B * lnR + SH_C * lnR * lnR * lnR);
  float tC   = tK - 273.15 + CAL_OFFSET_C;

  historial[idxHist] = tC;
  idxHist = (idxHist + 1) % VENTANA_S;
  if (nHist < VENTANA_S) nHist++;

  float mn = tC, mx = tC;
  for (byte i = 0; i < nHist; i++) {
    if (historial[i] < mn) mn = historial[i];
    if (historial[i] > mx) mx = historial[i];
  }
  bool estable = (nHist == VENTANA_S) && (mx - mn < 0.2);

  Serial.print(F("ADC: "));
  Serial.print(adc, 1);
  Serial.print(F("   R: "));
  Serial.print(rNtc, 0);
  Serial.print(F(" ohm   Temp: "));
  Serial.print(tC, 1);
  Serial.println(estable ? F(" C   [ESTABLE]") : F(" C   [estabilizando...]"));

  if (estable) {
    // Mismo campo que en el JSON de telemetria del doc
    Serial.print(F("{\"body_temp_c\":"));
    Serial.print(tC, 1);
    Serial.println(F("}"));
  }
}
