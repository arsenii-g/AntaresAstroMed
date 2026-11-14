// AstroMed - prueba de que todos los sensores estan conectados y funcionan
//
// Subelo al UNO y abre el Monitor serie a 115200.
//   1. Primero hace las pruebas automaticas: RTC, RC522, DHT11, termistor, LED + fotorresistencia
//      y HC-SR04. Cada una sale como [ OK ], [AVISO] o [FALLO], con lo que hay que revisar.
//   2. Despues pide que hagas cosas (pasar tarjeta, inclinar, pulsar...) y las va tachando.
//   Envia "r" en el Monitor serie para repetir las pruebas automaticas.
//
// Enlace con el ESP32: si el ESP32 tiene subido esp32_gateway, en SU Monitor serie
// deben salir estas mismas lineas con "[uno]" delante. Si salen, el cableado UNO -> ESP32 va bien.
//
// Libreria: MFRC522 (GithubCommunity). Mismos pines que firmware/uno_sensores/config.h.

#include <SPI.h>
#include <Wire.h>
#include <MFRC522.h>

const uint8_t PIN_TILT = 3, PIN_DHT = 4, PIN_US_TRIG = 5, PIN_US_ECHO = 6, PIN_BUTTON = 7;
const uint8_t PIN_PULSE_LED = 8, PIN_RFID_RST = 9, PIN_RFID_SS = 10;
const uint8_t PIN_NTC = A0, PIN_PULSE_LDR = A1;
const uint8_t DS1307_ADDR = 0x68;

// Termistor: mismos coeficientes que termistor_test.ino
const float NTC_R_FIXED = 10000.0, SH_A = 0.001129148, SH_B = 0.000234125, SH_C = 0.0000000876741;

MFRC522 rfid(PIN_RFID_SS, PIN_RFID_RST);

uint8_t nOk, nWarn, nFail;

void result(uint8_t kind, const __FlashStringHelper *name) {
  if (kind == 0) { Serial.print(F("[ OK ] ")); nOk++; }
  else if (kind == 1) { Serial.print(F("[AVISO] ")); nWarn++; }
  else { Serial.print(F("[FALLO] ")); nFail++; }
  Serial.print(name);
  Serial.print(F(": "));
}

// ---------------------------------------------------------------- utilidades

int readAnalogAvg(uint8_t pin, uint8_t n = 16) {
  long s = 0;
  for (uint8_t i = 0; i < n; i++) { s += analogRead(pin); delay(2); }
  return s / n;
}

// Un pin analogico sin nada conectado "flota": con el pull-up interno se va a 1023.
// Si hay un divisor de resistencias, el pull-up apenas lo mueve.
bool analogFloating(uint8_t pin) {
  pinMode(pin, INPUT_PULLUP);
  delay(5);
  int up = readAnalogAvg(pin, 8);
  pinMode(pin, INPUT);
  delay(5);
  int normal = readAnalogAvg(pin, 8);
  return up > 1005 && normal < 990;
}

float ntcCelsius(float adc) {
  float r = NTC_R_FIXED * (1023.0 / adc - 1.0);
  float lnR = log(r);
  return 1.0 / (SH_A + SH_B * lnR + SH_C * lnR * lnR * lnR) - 273.15;
}

float readDistanceCm(unsigned long timeoutUs = 25000) {
  digitalWrite(PIN_US_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_US_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_US_TRIG, LOW);
  unsigned long us = pulseIn(PIN_US_ECHO, HIGH, timeoutUs);
  return us == 0 ? -1 : us / 58.0;
}

static const uint16_t DHT_TIMEOUT = 0xFFFF;
// Cuenta ciclos mientras el pin esta en 'level' (0 es valido). DHT_TIMEOUT = se paso del tiempo.
static uint16_t dhtPulse(uint8_t level) {
  uint16_t c = 0;
  while (digitalRead(PIN_DHT) == level) {
    if (++c >= 3000) return DHT_TIMEOUT;   // ~10 ms
  }
  return c;
}

bool readDHT11(float &t, float &h) {
  uint8_t d[5] = {0, 0, 0, 0, 0};
  pinMode(PIN_DHT, OUTPUT);
  digitalWrite(PIN_DHT, LOW);
  delay(20);
  pinMode(PIN_DHT, INPUT_PULLUP);
  delayMicroseconds(40);
  bool ok = true;
  noInterrupts();
  // espera a que el sensor responda (bajo ~80 us, alto ~80 us)
  if (dhtPulse(HIGH) == DHT_TIMEOUT || dhtPulse(LOW) == DHT_TIMEOUT || dhtPulse(HIGH) == DHT_TIMEOUT) ok = false;
  for (uint8_t i = 0; ok && i < 40; i++) {
    uint16_t lo = dhtPulse(LOW), hi = dhtPulse(HIGH);
    if (lo == DHT_TIMEOUT || hi == DHT_TIMEOUT) { ok = false; break; }
    d[i / 8] <<= 1;
    if (hi > lo) d[i / 8] |= 1;
  }
  interrupts();
  if (!ok || (uint8_t)(d[0] + d[1] + d[2] + d[3]) != d[4]) return false;
  h = d[0] + d[1] * 0.1;
  t = (d[2] & 0x7F) + d[3] * 0.1;
  return true;
}

bool rtcReadSeconds(uint8_t &raw) {
  Wire.beginTransmission(DS1307_ADDR);
  Wire.write(0x00);
  if (Wire.endTransmission() != 0) return false;
  if (Wire.requestFrom(DS1307_ADDR, (uint8_t)1) != 1) return false;
  raw = Wire.read();
  return true;
}

// ---------------------------------------------------------------- pruebas automaticas

int ledOnLevel = -1;     // luz en la LDR con el LED encendido (para la prueba del dedo)
float ntcStart = -100;   // temperatura inicial (para la prueba de apretar el termistor)

void testRtc() {
  uint8_t s1, s2;
  if (!rtcReadSeconds(s1)) {
    result(2, F("RTC DS1307"));
    Serial.println(F("no responde. Revisa SDA->A4, SCL->A5, VCC->5V, GND, y que tenga pila."));
    return;
  }
  bool wasStopped = s1 & 0x80;
  if (wasStopped) {  // oscilador parado: arrancarlo sin tocar el resto de la hora
    Wire.beginTransmission(DS1307_ADDR);
    Wire.write(0x00);
    Wire.write(s1 & 0x7F);
    Wire.endTransmission();
  }
  delay(1200);
  if (!rtcReadSeconds(s2)) {
    result(2, F("RTC DS1307"));
    Serial.println(F("responde a ratos. Revisa los cables SDA/SCL."));
  } else if ((s2 & 0x7F) == (s1 & 0x7F)) {
    result(2, F("RTC DS1307"));
    Serial.println(F("responde pero la hora no avanza. Pon una pila CR2032 (sin pila algunos no funcionan)."));
  } else {
    result(0, F("RTC DS1307"));
    Serial.println(wasStopped ? F("estaba parado, lo he arrancado y ya avanza.") : F("responde y la hora avanza."));
  }
}

void testRfid() {
  rfid.PCD_Init();
  delay(50);
  byte v = rfid.PCD_ReadRegister(MFRC522::VersionReg);
  if (v == 0x00 || v == 0xFF) {
    result(2, F("RC522"));
    Serial.print(F("no responde (version 0x"));
    Serial.print(v, HEX);
    Serial.println(F("). Revisa SDA->D10, SCK->D13, MOSI->D11, MISO->D12, RST->D9, 3.3V, GND."));
    return;
  }
  rfid.PCD_SetAntennaGain(rfid.RxGain_max);

  // ¿Le llegan las escrituras? PCD_Init escribe estos registros del temporizador:
  // deben valer 80 A9 03 E8 si MOSI y SCK van bien.
  byte r[4] = {rfid.PCD_ReadRegister(MFRC522::TModeReg), rfid.PCD_ReadRegister(MFRC522::TPrescalerReg),
               rfid.PCD_ReadRegister(MFRC522::TReloadRegH), rfid.PCD_ReadRegister(MFRC522::TReloadRegL)};
  byte tx = rfid.PCD_ReadRegister(MFRC522::TxControlReg);
  Serial.print(F("        RC522 detalle: registros "));
  for (uint8_t i = 0; i < 4; i++) { Serial.print(r[i], HEX); Serial.print(' '); }
  Serial.print(F("(deben ser 80 A9 3 E8), antena "));
  Serial.println((tx & 0x03) == 0x03 ? F("encendida") : F("APAGADA"));
  if (r[0] != 0x80 || r[1] != 0xA9 || r[2] != 0x03 || r[3] != 0xE8) {
    result(2, F("RC522"));
    Serial.println(F("lee pero las escrituras no llegan bien: revisa MOSI->D11 y SCK->D13 (y sus soldaduras)."));
    return;
  }

  bool known = v == 0x88 || v == 0x90 || v == 0x91 || v == 0x92 || v == 0xB2;
  result(known ? 0 : 1, F("RC522"));
  Serial.print(F("responde, version 0x"));
  Serial.print(v, HEX);
  Serial.println(known ? F(". Falta pasar una tarjeta (abajo).") : F(" (clon, suele funcionar). Falta pasar una tarjeta (abajo)."));
}

void testDht() {
  float t, h;
  bool ok = false;
  for (uint8_t i = 0; i < 3 && !ok; i++) {
    ok = readDHT11(t, h);
    if (!ok) delay(1200);
  }
  if (!ok) {
    // Diagnostico: nivel en reposo y si el sensor contesta a la senal de inicio
    pinMode(PIN_DHT, INPUT);
    delay(5);
    int idle = digitalRead(PIN_DHT);
    // ¿Hay algo en D4? Lo bajo un instante y miro si vuelve solo a 5 V (resistencia del modulo)
    pinMode(PIN_DHT, OUTPUT);
    digitalWrite(PIN_DHT, LOW);
    delayMicroseconds(50);
    pinMode(PIN_DHT, INPUT);
    delayMicroseconds(20);
    bool hasPullup = digitalRead(PIN_DHT) == HIGH;
    delay(1200);
    pinMode(PIN_DHT, OUTPUT);
    digitalWrite(PIN_DHT, LOW);
    delay(20);
    pinMode(PIN_DHT, INPUT_PULLUP);
    uint32_t t0 = micros();
    bool answered = false;
    while (micros() - t0 < 400) {
      if (digitalRead(PIN_DHT) == LOW) { answered = true; break; }
    }
    result(2, F("DHT11"));
    if (idle == LOW) {
      Serial.println(F("D4 esta a 0 V en reposo: DATA toca GND, o el sensor esta girado (mira la serigrafia S / + / -)."));
    } else if (!answered && !hasPullup) {
      Serial.println(F("D4 no llega a ningun modulo: el cable de S/DATA no esta en D4 o no hace contacto."));
      Serial.println(F("        (Si es el sensor azul suelto de 4 patas, le falta la resistencia de 10k entre DATA y 5V.)"));
    } else if (!answered) {
      Serial.println(F("D4 si llega al modulo, pero el sensor no contesta: revisa + -> 5V y - -> GND (alimentacion)."));
      Serial.println(F("        Si estan bien, el sensor puede estar roto o ser otro modelo (el DHT22 es blanco)."));
    } else {
      Serial.println(F("contesta pero los datos llegan mal: cable flojo o largo. Sensor suelto de 4 patas: 10k entre DATA y 5V."));
    }
    return;
  }
  bool plausible = t >= 0 && t <= 50 && h >= 5 && h <= 95;
  result(plausible ? 0 : 1, F("DHT11"));
  Serial.print(t, 1);
  Serial.print(F(" C, "));
  Serial.print(h, 0);
  Serial.println(plausible ? F(" % de humedad.") : F(" %. Valores raros, revisa el sensor."));
}

void testNtc() {
  if (analogFloating(PIN_NTC)) {
    result(2, F("Termistor (A0)"));
    Serial.println(F("A0 no tiene nada conectado. Monta 5V -> termistor -> A0 -> 10k -> GND."));
    return;
  }
  int adc = readAnalogAvg(PIN_NTC);
  if (adc < 5) {
    result(2, F("Termistor (A0)"));
    Serial.println(F("A0 casi a 0 V: el termistor no llega a 5V o esta suelto."));
  } else if (adc > 1018) {
    result(2, F("Termistor (A0)"));
    Serial.println(F("A0 casi a 5 V: la resistencia de 10k no llega a GND."));
  } else {
    float t = ntcCelsius(adc);
    ntcStart = t;
    bool plausible = t > 5 && t < 45;
    result(plausible ? 0 : 1, F("Termistor (A0)"));
    Serial.print(t, 1);
    Serial.println(plausible ? F(" C. Falta apretarlo con los dedos (abajo).")
                             : F(" C, valor raro: revisa que la resistencia sea de 10k."));
  }
}

void testPulseLedLdr() {
  if (analogFloating(PIN_PULSE_LDR)) {
    result(2, F("Fotorresistencia del pulso (A1)"));
    Serial.println(F("A1 no tiene nada conectado. Monta 5V -> fotorresistencia -> A1 -> 10k -> GND."));
    digitalWrite(PIN_PULSE_LED, HIGH);
    return;
  }
  long off = 0, on = 0;
  for (uint8_t i = 0; i < 3; i++) {
    digitalWrite(PIN_PULSE_LED, LOW);
    delay(300);
    off += readAnalogAvg(PIN_PULSE_LDR);
    digitalWrite(PIN_PULSE_LED, HIGH);
    delay(300);
    on += readAnalogAvg(PIN_PULSE_LDR);
  }
  off /= 3;
  on /= 3;
  ledOnLevel = on;
  if (on < 5 && off < 5) {
    result(2, F("Fotorresistencia del pulso (A1)"));
    Serial.println(F("A1 siempre a 0 V: la fotorresistencia no llega a 5V."));
  } else if (on > 1018 && off > 1018) {
    result(2, F("Fotorresistencia del pulso (A1)"));
    Serial.println(F("A1 siempre a 5 V: la resistencia de 10k no llega a GND."));
  } else if (on - off > 15) {
    result(0, F("LED + fotorresistencia del pulso"));
    Serial.print(F("la luz pasa de "));
    Serial.print(off);
    Serial.print(F(" (LED apagado) a "));
    Serial.print(on);
    Serial.println(F(" (encendido). Falta poner el dedo (abajo)."));
  } else {
    result(1, F("LED + fotorresistencia del pulso"));
    Serial.print(F("no se nota el LED ("));
    Serial.print(off);
    Serial.print(F(" -> "));
    Serial.print(on);
    Serial.println(F("). Quita el dedo, pon el LED mirando a la fotorresistencia, y revisa:"));
    Serial.println(F("        D8 -> 220 ohm -> pata LARGA del LED, pata corta -> GND. Mira si el LED se enciende."));
  }
}

void testUltrasonic() {
  float best = -1;
  for (uint8_t i = 0; i < 6; i++) {
    float d = readDistanceCm();
    if (d > 0) best = d;
    delay(60);
  }
  if (best > 0) {
    result(0, F("HC-SR04"));
    Serial.print(best, 1);
    Serial.println(F(" cm. Falta subir y bajar la mano (abajo)."));
  } else {
    result(1, F("HC-SR04"));
    Serial.println(F("sin eco. Pon la mano a 20 cm delante; si sigue igual, revisa TRIG->D5, ECHO->D6, VCC->5V."));
  }
}

void runAutoTests() {
  nOk = nWarn = nFail = 0;
  Serial.println();
  Serial.println(F("=========== PRUEBA DE SENSORES AstroMed ==========="));
  Serial.println(F("Quita el dedo del LED y no toques nada durante 10 s..."));
  Serial.println();
  testRtc();
  testRfid();
  testDht();
  testNtc();
  testPulseLedLdr();
  testUltrasonic();
  Serial.println();
  Serial.print(F("Automaticas: "));
  Serial.print(nOk);
  Serial.print(F(" OK, "));
  Serial.print(nWarn);
  Serial.print(F(" avisos, "));
  Serial.print(nFail);
  Serial.println(F(" fallos."));
  Serial.println();
  Serial.println(F("--- Ahora haz esto (se van tachando): ---"));
  Serial.println(F("  1. Pasa una tarjeta por el RC522"));
  Serial.println(F("  2. Inclina o agita el interruptor de inclinacion"));
  Serial.println(F("  3. Pulsa el pulsador (si lo has puesto)"));
  Serial.println(F("  4. Baja la mano a menos de 15 cm del HC-SR04 y subela a mas de 28 cm"));
  Serial.println(F("  5. Aprieta el termistor con los dedos (debe subir 1 C)"));
  Serial.println(F("  6. Pon el dedo entre el LED y la fotorresistencia (la luz debe bajar)"));
  Serial.println(F("Envia 'r' para repetir las pruebas automaticas."));
  Serial.println();
}

// ---------------------------------------------------------------- pruebas con interaccion

bool doneCard, doneTilt, doneButton, doneUsLow, doneUsHigh, doneNtc, doneFinger, allDoneShown;
int lastTilt, lastButton;
uint32_t nextUs, nextStatus, nextCardPoll;
float lastDist = -1;

void resetInteractive() {
  doneCard = doneTilt = doneButton = doneUsLow = doneUsHigh = doneNtc = doneFinger = allDoneShown = false;
  lastTilt = digitalRead(PIN_TILT);
  lastButton = digitalRead(PIN_BUTTON);
}

void mark(bool &flag, const __FlashStringHelper *msg) {
  if (flag) return;
  flag = true;
  Serial.print(F("[ OK ] "));
  Serial.println(msg);
}

void checkCard() {
  if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) return;
  char uid[21];
  static const char hex[] = "0123456789ABCDEF";
  uint8_t n = rfid.uid.size > 10 ? 10 : rfid.uid.size;
  for (uint8_t i = 0; i < n; i++) {
    uid[2 * i] = hex[rfid.uid.uidByte[i] >> 4];
    uid[2 * i + 1] = hex[rfid.uid.uidByte[i] & 0x0F];
  }
  uid[2 * n] = '\0';
  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
  Serial.print(F("[ OK ] Tarjeta leida: "));
  Serial.print(uid);
  if (strcmp(uid, "F3786E09") == 0) Serial.println(F(" (Tripulante 1)"));
  else if (strcmp(uid, "336F8312") == 0) Serial.println(F(" (Tripulante 2)"));
  else Serial.println(F(" (no registrada en el documento)"));
  doneCard = true;
}

void printStatus() {
  int ntcAdc = readAnalogAvg(PIN_NTC, 8);
  int light = readAnalogAvg(PIN_PULSE_LDR, 8);
  Serial.print(F("  ahora: dist="));
  if (lastDist < 0) Serial.print(F("sin eco"));
  else { Serial.print(lastDist, 1); Serial.print(F("cm")); }
  Serial.print(F(" incl="));
  Serial.print(digitalRead(PIN_TILT));
  Serial.print(F(" pulsador="));
  Serial.print(digitalRead(PIN_BUTTON) == LOW ? F("pulsado") : F("suelto"));
  Serial.print(F(" termistor="));
  if (ntcAdc > 5 && ntcAdc < 1018) { Serial.print(ntcCelsius(ntcAdc), 1); Serial.print(F("C")); }
  else Serial.print(F("?"));
  Serial.print(F(" luz_pulso="));
  Serial.print(light);
  Serial.print(F("  | falta:"));
  if (!doneCard) Serial.print(F(" tarjeta"));
  if (!doneTilt) Serial.print(F(" inclinacion"));
  if (!doneButton) Serial.print(F(" pulsador"));
  if (!doneUsLow || !doneUsHigh) Serial.print(F(" mano-HC-SR04"));
  if (!doneNtc) Serial.print(F(" apretar-termistor"));
  if (!doneFinger) Serial.print(F(" dedo-pulso"));
  Serial.println();
}

// ---------------------------------------------------------------- setup / loop

void setup() {
  Serial.begin(115200);
  pinMode(PIN_TILT, INPUT_PULLUP);
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  pinMode(PIN_US_TRIG, OUTPUT);
  pinMode(PIN_US_ECHO, INPUT);
  pinMode(PIN_PULSE_LED, OUTPUT);
  digitalWrite(PIN_PULSE_LED, HIGH);
  Wire.begin();
  Wire.setWireTimeout(25000, true);   // que no se cuelgue si SDA/SCL estan mal
  SPI.begin();
  delay(1000);                        // el DHT11 necesita 1 s tras encenderse
  runAutoTests();
  resetInteractive();
}

void loop() {
  uint32_t now = millis();

  while (Serial.available()) {
    char c = Serial.read();
    if (c == 'r' || c == 'R') { runAutoTests(); resetInteractive(); }
  }

  if ((int32_t)(now - nextCardPoll) >= 0) { nextCardPoll = now + 100; checkCard(); }

  int t = digitalRead(PIN_TILT);
  if (t != lastTilt) { lastTilt = t; mark(doneTilt, F("Interruptor de inclinacion: cambia al moverlo.")); }

  int b = digitalRead(PIN_BUTTON);
  if (b != lastButton) {
    lastButton = b;
    if (b == LOW) mark(doneButton, F("Pulsador: detectado."));
  }

  if ((int32_t)(now - nextUs) >= 0) {
    nextUs = now + 80;
    lastDist = readDistanceCm(7000);
    if (lastDist > 0 && lastDist < 15) mark(doneUsLow, F("HC-SR04: mano cerca (< 15 cm)."));
    if (doneUsLow && (lastDist < 0 || lastDist > 28)) mark(doneUsHigh, F("HC-SR04: mano lejos (> 28 cm). Contara flexiones bien."));
  }

  if ((int32_t)(now - nextStatus) >= 0) {
    nextStatus = now + 2000;
    int ntcAdc = readAnalogAvg(PIN_NTC, 8);
    if (ntcStart > -100 && ntcAdc > 5 && ntcAdc < 1018 && ntcCelsius(ntcAdc) > ntcStart + 1.0)
      mark(doneNtc, F("Termistor: sube al apretarlo."));
    int light = readAnalogAvg(PIN_PULSE_LDR, 8);
    if (ledOnLevel > 50 && light < ledOnLevel * 0.8)
      mark(doneFinger, F("Pulso: la luz baja al poner el dedo."));
    printStatus();
  }

  if (!allDoneShown && doneCard && doneTilt && doneButton && doneUsLow && doneUsHigh && doneNtc && doneFinger) {
    allDoneShown = true;
    Serial.println();
    if (nFail == 0) Serial.println(F("=========== TODO CONECTADO Y FUNCIONANDO ==========="));
    else Serial.println(F("=== Las pruebas con la mano van bien, pero arriba hay FALLOS que revisar ==="));
    Serial.println(F("Ya puedes subir firmware/uno_sensores (con PRUEBA_RFID_US a 0)."));
    Serial.println();
  }
}
