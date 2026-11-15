// AstroMed - test that all the sensors are connected and working
//
// Upload it to the UNO and open the Serial Monitor at 115200.
//   1. First it runs the automatic tests: RTC, RC522, DHT11, thermistor, LED + photoresistor
//      and HC-SR04. Each one shows as [ OK ], [WARN] or [FAIL], with what to check.
//   2. Then it asks you to do things (scan a card, tilt, press...) and checks them off.
//   Send "r" in the Serial Monitor to repeat the automatic tests.
//
// ESP32 link: if the ESP32 has esp32_gateway uploaded, ITS Serial Monitor
// should show these same lines prefixed with "[uno]". If they appear, the UNO -> ESP32 wiring is fine.
//
// Library: MFRC522 (GithubCommunity). Same pins as firmware/uno_sensors/config.h.

#include <SPI.h>
#include <Wire.h>
#include <MFRC522.h>

const uint8_t PIN_TILT = 3, PIN_DHT = 4, PIN_US_TRIG = 5, PIN_US_ECHO = 6, PIN_BUTTON = 7;
const uint8_t PIN_PULSE_LED = 8, PIN_RFID_RST = 9, PIN_RFID_SS = 10;
const uint8_t PIN_NTC = A0, PIN_PULSE_LDR = A1;
const uint8_t DS1307_ADDR = 0x68;

// Thermistor: same coefficients as thermistor_test.ino
const float NTC_R_FIXED = 10000.0, SH_A = 0.001129148, SH_B = 0.000234125, SH_C = 0.0000000876741;

MFRC522 rfid(PIN_RFID_SS, PIN_RFID_RST);

uint8_t nOk, nWarn, nFail;

void result(uint8_t kind, const __FlashStringHelper *name) {
  if (kind == 0) { Serial.print(F("[ OK ] ")); nOk++; }
  else if (kind == 1) { Serial.print(F("[WARN] ")); nWarn++; }
  else { Serial.print(F("[FAIL] ")); nFail++; }
  Serial.print(name);
  Serial.print(F(": "));
}

// ---------------------------------------------------------------- utilities

int readAnalogAvg(uint8_t pin, uint8_t n = 16) {
  long s = 0;
  for (uint8_t i = 0; i < n; i++) { s += analogRead(pin); delay(2); }
  return s / n;
}

// An analog pin with nothing connected "floats": with the internal pull-up it goes to 1023.
// If there is a resistor divider, the pull-up barely moves it.
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
// Counts cycles while the pin is at 'level' (0 is valid). DHT_TIMEOUT = timed out.
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
  // wait for the sensor to respond (low ~80 us, high ~80 us)
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

// ---------------------------------------------------------------- automatic tests

int ledOnLevel = -1;     // light on the LDR with the LED on (for the finger test)
float ntcStart = -100;   // starting temperature (for the thermistor squeeze test)

void testRtc() {
  uint8_t s1, s2;
  if (!rtcReadSeconds(s1)) {
    result(2, F("RTC DS1307"));
    Serial.println(F("no response. Check SDA->A4, SCL->A5, VCC->5V, GND, and that it has a battery."));
    return;
  }
  bool wasStopped = s1 & 0x80;
  if (wasStopped) {  // oscillator stopped: start it without touching the rest of the time
    Wire.beginTransmission(DS1307_ADDR);
    Wire.write(0x00);
    Wire.write(s1 & 0x7F);
    Wire.endTransmission();
  }
  delay(1200);
  if (!rtcReadSeconds(s2)) {
    result(2, F("RTC DS1307"));
    Serial.println(F("responds intermittently. Check the SDA/SCL wires."));
  } else if ((s2 & 0x7F) == (s1 & 0x7F)) {
    result(2, F("RTC DS1307"));
    Serial.println(F("responds but the time does not advance. Insert a CR2032 battery (some do not work without one)."));
  } else {
    result(0, F("RTC DS1307"));
    Serial.println(wasStopped ? F("was stopped, I started it and it now advances.") : F("responds and the time advances."));
  }
}

void testRfid() {
  rfid.PCD_Init();
  delay(50);
  byte v = rfid.PCD_ReadRegister(MFRC522::VersionReg);
  if (v == 0x00 || v == 0xFF) {
    result(2, F("RC522"));
    Serial.print(F("no response (version 0x"));
    Serial.print(v, HEX);
    Serial.println(F(")  Check SDA->D10, SCK->D13, MOSI->D11, MISO->D12, RST->D9, 3.3V, GND."));
    return;
  }
  rfid.PCD_SetAntennaGain(rfid.RxGain_max);

  // Do the writes reach it? PCD_Init writes these timer registers:
  // they should read 80 A9 03 E8 if MOSI and SCK are fine.
  byte r[4] = {rfid.PCD_ReadRegister(MFRC522::TModeReg), rfid.PCD_ReadRegister(MFRC522::TPrescalerReg),
               rfid.PCD_ReadRegister(MFRC522::TReloadRegH), rfid.PCD_ReadRegister(MFRC522::TReloadRegL)};
  byte tx = rfid.PCD_ReadRegister(MFRC522::TxControlReg);
  Serial.print(F("        RC522 detail: registers "));
  for (uint8_t i = 0; i < 4; i++) { Serial.print(r[i], HEX); Serial.print(' '); }
  Serial.print(F("(should be 80 A9 3 E8), antenna "));
  Serial.println((tx & 0x03) == 0x03 ? F("on") : F("OFF"));
  if (r[0] != 0x80 || r[1] != 0xA9 || r[2] != 0x03 || r[3] != 0xE8) {
    result(2, F("RC522"));
    Serial.println(F("reads but writes do not arrive correctly: check MOSI->D11 and SCK->D13 (and their solder joints)."));
    return;
  }

  bool known = v == 0x88 || v == 0x90 || v == 0x91 || v == 0x92 || v == 0xB2;
  result(known ? 0 : 1, F("RC522"));
  Serial.print(F("responds, version 0x"));
  Serial.print(v, HEX);
  Serial.println(known ? F(". Still need to scan a card (below).") : F(" (clone, usually works). Still need to scan a card (below)."));
}

void testDht() {
  float t, h;
  bool ok = false;
  for (uint8_t i = 0; i < 3 && !ok; i++) {
    ok = readDHT11(t, h);
    if (!ok) delay(1200);
  }
  if (!ok) {
    // Diagnostics: idle level and whether the sensor answers the start signal
    pinMode(PIN_DHT, INPUT);
    delay(5);
    int idle = digitalRead(PIN_DHT);
    // Is anything on D4? Pull it low briefly and check whether it returns to 5 V by itself (module resistor)
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
      Serial.println(F("D4 is at 0 V at idle: DATA touches GND, or the sensor is reversed (check the S / + / - silkscreen)."));
    } else if (!answered && !hasPullup) {
      Serial.println(F("D4 does not reach any module: the S/DATA wire is not on D4 or is not making contact."));
      Serial.println(F("        (If it is the loose blue 4-pin sensor, it is missing the 10k resistor between DATA and 5V.)"));
    } else if (!answered) {
      Serial.println(F("D4 does reach the module, but the sensor does not answer: check + -> 5V and - -> GND (power)."));
      Serial.println(F("        If those are fine, the sensor may be broken or a different model (the DHT22 is white)."));
    } else {
      Serial.println(F("answers but the data arrives corrupted: loose or long wire. Loose 4-pin sensor: 10k between DATA and 5V."));
    }
    return;
  }
  bool plausible = t >= 0 && t <= 50 && h >= 5 && h <= 95;
  result(plausible ? 0 : 1, F("DHT11"));
  Serial.print(t, 1);
  Serial.print(F(" C, "));
  Serial.print(h, 0);
  Serial.println(plausible ? F(" % humidity.") : F(" %. Odd values, check the sensor."));
}

void testNtc() {
  if (analogFloating(PIN_NTC)) {
    result(2, F("Thermistor (A0)"));
    Serial.println(F("A0 has nothing connected. Wire 5V -> thermistor -> A0 -> 10k -> GND."));
    return;
  }
  int adc = readAnalogAvg(PIN_NTC);
  if (adc < 5) {
    result(2, F("Thermistor (A0)"));
    Serial.println(F("A0 near 0 V: the thermistor is not reaching 5V or is loose."));
  } else if (adc > 1018) {
    result(2, F("Thermistor (A0)"));
    Serial.println(F("A0 near 5 V: the 10k resistor is not reaching GND."));
  } else {
    float t = ntcCelsius(adc);
    ntcStart = t;
    bool plausible = t > 5 && t < 45;
    result(plausible ? 0 : 1, F("Thermistor (A0)"));
    Serial.print(t, 1);
    Serial.println(plausible ? F(" C. Still need to squeeze it with your fingers (below).")
                             : F(" C, odd value: check that the resistor is 10k."));
  }
}

void testPulseLedLdr() {
  if (analogFloating(PIN_PULSE_LDR)) {
    result(2, F("Pulse photoresistor (A1)"));
    Serial.println(F("A1 has nothing connected. Wire 5V -> photoresistor -> A1 -> 10k -> GND."));
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
    result(2, F("Pulse photoresistor (A1)"));
    Serial.println(F("A1 always at 0 V: the photoresistor is not reaching 5V."));
  } else if (on > 1018 && off > 1018) {
    result(2, F("Pulse photoresistor (A1)"));
    Serial.println(F("A1 always at 5 V: the 10k resistor is not reaching GND."));
  } else if (on - off > 15) {
    result(0, F("Pulse LED + photoresistor"));
    Serial.print(F("light goes from "));
    Serial.print(off);
    Serial.print(F(" (LED off) to "));
    Serial.print(on);
    Serial.println(F(" (on). Still need to place a finger (below)."));
  } else {
    result(1, F("Pulse LED + photoresistor"));
    Serial.print(F("LED not noticeable ("));
    Serial.print(off);
    Serial.print(F(" -> "));
    Serial.print(on);
    Serial.println(F("). Remove your finger, point the LED at the photoresistor, and check:"));
    Serial.println(F("        D8 -> 220 ohm -> LONG LED leg, short leg -> GND. See if the LED lights up."));
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
    Serial.println(F(" cm. Still need to move your hand up and down (below)."));
  } else {
    result(1, F("HC-SR04"));
    Serial.println(F("no echo. Put your hand 20 cm in front; if nothing changes, check TRIG->D5, ECHO->D6, VCC->5V."));
  }
}

void runAutoTests() {
  nOk = nWarn = nFail = 0;
  Serial.println();
  Serial.println(F("=========== AstroMed SENSOR TEST ==========="));
  Serial.println(F("Take your finger off the LED and do not touch anything for 10 s..."));
  Serial.println();
  testRtc();
  testRfid();
  testDht();
  testNtc();
  testPulseLedLdr();
  testUltrasonic();
  Serial.println();
  Serial.print(F("Automatic: "));
  Serial.print(nOk);
  Serial.print(F(" OK, "));
  Serial.print(nWarn);
  Serial.print(F(" warnings, "));
  Serial.print(nFail);
  Serial.println(F(" failures."));
  Serial.println();
  Serial.println(F("--- Now do this (they get checked off): ---"));
  Serial.println(F("  1. Scan a card on the RC522"));
  Serial.println(F("  2. Tilt or shake the tilt switch"));
  Serial.println(F("  3. Press the button (if you installed it)"));
  Serial.println(F("  4. Lower your hand to under 15 cm from the HC-SR04 and raise it above 28 cm"));
  Serial.println(F("  5. Squeeze the thermistor with your fingers (it should rise 1 C)"));
  Serial.println(F("  6. Put your finger between the LED and the photoresistor (the light should drop)"));
  Serial.println(F("Send 'r' to repeat the automatic tests."));
  Serial.println();
}

// ---------------------------------------------------------------- interactive tests

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
  Serial.print(F("[ OK ] Card read: "));
  Serial.print(uid);
  if (strcmp(uid, "F3786E09") == 0) Serial.println(F(" (Crew member 1)"));
  else if (strcmp(uid, "336F8312") == 0) Serial.println(F(" (Crew member 2)"));
  else Serial.println(F(" (not registered in the doc)"));
  doneCard = true;
}

void printStatus() {
  int ntcAdc = readAnalogAvg(PIN_NTC, 8);
  int light = readAnalogAvg(PIN_PULSE_LDR, 8);
  Serial.print(F("  now: dist="));
  if (lastDist < 0) Serial.print(F("no echo"));
  else { Serial.print(lastDist, 1); Serial.print(F("cm")); }
  Serial.print(F(" tilt="));
  Serial.print(digitalRead(PIN_TILT));
  Serial.print(F(" button="));
  Serial.print(digitalRead(PIN_BUTTON) == LOW ? F("pressed") : F("released"));
  Serial.print(F(" thermistor="));
  if (ntcAdc > 5 && ntcAdc < 1018) { Serial.print(ntcCelsius(ntcAdc), 1); Serial.print(F("C")); }
  else Serial.print(F("?"));
  Serial.print(F(" pulse_light="));
  Serial.print(light);
  Serial.print(F("  | missing:"));
  if (!doneCard) Serial.print(F(" card"));
  if (!doneTilt) Serial.print(F(" tilt"));
  if (!doneButton) Serial.print(F(" button"));
  if (!doneUsLow || !doneUsHigh) Serial.print(F(" hand-HC-SR04"));
  if (!doneNtc) Serial.print(F(" squeeze-thermistor"));
  if (!doneFinger) Serial.print(F(" pulse-finger"));
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
  Wire.setWireTimeout(25000, true);   // so it does not hang if SDA/SCL are wrong
  SPI.begin();
  delay(1000);                        // the DHT11 needs 1 s after power-up
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
  if (t != lastTilt) { lastTilt = t; mark(doneTilt, F("Tilt switch: changes when moved.")); }

  int b = digitalRead(PIN_BUTTON);
  if (b != lastButton) {
    lastButton = b;
    if (b == LOW) mark(doneButton, F("Button: detected."));
  }

  if ((int32_t)(now - nextUs) >= 0) {
    nextUs = now + 80;
    lastDist = readDistanceCm(7000);
    if (lastDist > 0 && lastDist < 15) mark(doneUsLow, F("HC-SR04: hand close (< 15 cm)."));
    if (doneUsLow && (lastDist < 0 || lastDist > 28)) mark(doneUsHigh, F("HC-SR04: hand far (> 28 cm). It will count push-ups correctly."));
  }

  if ((int32_t)(now - nextStatus) >= 0) {
    nextStatus = now + 2000;
    int ntcAdc = readAnalogAvg(PIN_NTC, 8);
    if (ntcStart > -100 && ntcAdc > 5 && ntcAdc < 1018 && ntcCelsius(ntcAdc) > ntcStart + 1.0)
      mark(doneNtc, F("Thermistor: rises when squeezed."));
    int light = readAnalogAvg(PIN_PULSE_LDR, 8);
    if (ledOnLevel > 50 && light < ledOnLevel * 0.8)
      mark(doneFinger, F("Pulse: the light drops when a finger is placed."));
    printStatus();
  }

  if (!allDoneShown && doneCard && doneTilt && doneButton && doneUsLow && doneUsHigh && doneNtc && doneFinger) {
    allDoneShown = true;
    Serial.println();
    if (nFail == 0) Serial.println(F("=========== EVERYTHING CONNECTED AND WORKING ==========="));
    else Serial.println(F("=== The hands-on tests pass, but there are FAILURES above to check ==="));
    Serial.println(F("You can now upload firmware/uno_sensors (with TEST_RFID_US set to 0)."));
    Serial.println();
  }
}
