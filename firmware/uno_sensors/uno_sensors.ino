// AstroMed - Arduino UNO firmware
//
// Measures the crew member (RFID, pulse, temperature, motion, push-ups)
// and the cabin (DHT11), and sends one JSON line per message over serial (115200):
//
//   {"t":"tel", ...}   telemetry every 2 s
//   {"t":"evt", ...}   events: crew_checkin, inactivity, exercise_summary
//
// The ESP32 reads those lines, adds device_id and ts (NTP time) and sends them to the backend.
// Lines starting with '#' are debug output and the ESP32 ignores them.
//
// Required library: MFRC522 (GithubCommunity). The DHT11 and the DS1307 RTC are read
// directly, without libraries.
//
// The HC-SR04 sits on the floor under the chest and only counts push-ups. Breathing is not
// measured: resp_rate_bpm is always null so the JSON format is not broken.
//
// Button (D7, optional): if held down at power-on, the mission time is reset
// (met_s = 0).
//
// NOTE: the UNO TX (D1) goes to the ESP32 and also to USB, so in the Serial Monitor
// you see exactly what the ESP32 receives. You can upload the sketch without
// disconnecting the ESP32 because only TX is connected.

#include <SPI.h>
#include <Wire.h>
#include <MFRC522.h>
#include <math.h>
#include "config.h"

MFRC522 rfid(PIN_RFID_SS, PIN_RFID_RST);

// ============================================================================
// Utilities
// ============================================================================

// Ring buffer of timestamps (beats)
struct TimeRing {
  static const uint8_t N = 20;
  uint32_t t[N];
  uint8_t head = 0, count = 0;
  void clear() { head = 0; count = 0; }
  void push(uint32_t v) {
    t[head] = v;
    head = (head + 1) % N;
    if (count < N) count++;
  }
  uint32_t get(uint8_t i) const { return t[(head + N - count + i) % N]; }  // 0 = the oldest
};

static inline bool due(uint32_t now, uint32_t &next, uint32_t period) {
  if ((int32_t)(now - next) < 0) return false;
  next = now + period;
  return true;
}

// ============================================================================
// General state
// ============================================================================

char crewId[21] = "";               // UID in hexadecimal; "" = nobody

// ============================================================================
// DS1307 RTC (mission time). No library: direct I2C.
// ============================================================================

const uint8_t DS1307_ADDR = 0x68;
const uint8_t NVRAM_MAGIC = 0x5A;   // in the DS1307 NVRAM (0x08): magic + 4 start bytes
bool rtcOk = false;
uint32_t missionStart = 0;          // seconds since 2000-01-01 (only the difference matters)

static uint8_t bcd2bin(uint8_t v) { return (v >> 4) * 10 + (v & 0x0F); }

static uint32_t daysFrom2000(uint16_t y, uint8_t m, uint8_t d) {
  static const uint8_t dim[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
  uint32_t days = d - 1;
  for (uint16_t yy = 2000; yy < y; yy++) days += (yy % 4 == 0) ? 366 : 365;
  for (uint8_t mm = 1; mm < m; mm++) days += (mm == 2 && y % 4 == 0) ? 29 : dim[mm - 1];
  return days;
}

bool rtcReadRegs(uint8_t reg, uint8_t *buf, uint8_t n) {
  Wire.beginTransmission(DS1307_ADDR);
  Wire.write(reg);
  if (Wire.endTransmission() != 0) return false;
  if (Wire.requestFrom(DS1307_ADDR, n) != n) return false;
  for (uint8_t i = 0; i < n; i++) buf[i] = Wire.read();
  return true;
}

bool rtcWriteRegs(uint8_t reg, const uint8_t *buf, uint8_t n) {
  Wire.beginTransmission(DS1307_ADDR);
  Wire.write(reg);
  for (uint8_t i = 0; i < n; i++) Wire.write(buf[i]);
  return Wire.endTransmission() == 0;
}

bool rtcNow(uint32_t &secs) {
  uint8_t r[7];
  if (!rtcReadRegs(0x00, r, 7)) return false;
  uint8_t s = bcd2bin(r[0] & 0x7F), mi = bcd2bin(r[1] & 0x7F);
  uint8_t h;
  if (r[2] & 0x40) {  // 12 h mode
    h = bcd2bin(r[2] & 0x1F) % 12;
    if (r[2] & 0x20) h += 12;
  } else {
    h = bcd2bin(r[2] & 0x3F);
  }
  uint8_t d = bcd2bin(r[4] & 0x3F), mo = bcd2bin(r[5] & 0x1F);
  uint16_t y = 2000 + bcd2bin(r[6]);
  if (mo < 1 || mo > 12 || d < 1 || d > 31) return false;
  secs = daysFrom2000(y, mo, d) * 86400UL + h * 3600UL + mi * 60UL + s;
  return true;
}

void rtcSetup(bool resetMission) {
  Wire.begin();
  uint8_t sec;
  if (!rtcReadRegs(0x00, &sec, 1)) {
    rtcOk = false;
    Serial.println(F("# DS1307 RTC not detected: met_s comes from millis()"));
    return;
  }
  rtcOk = true;
  if (sec & 0x80) {  // oscillator stopped (new battery or no battery): start it at 2000-01-01
    const uint8_t zero[7] = {0x00, 0x00, 0x00, 0x01, 0x01, 0x01, 0x00};
    rtcWriteRegs(0x00, zero, 7);
    resetMission = true;
    Serial.println(F("# RTC stopped: starting it"));
  }
  uint8_t nv[5];
  bool haveNv = rtcReadRegs(0x08, nv, 5) && nv[0] == NVRAM_MAGIC;
  uint32_t now;
  if (!rtcNow(now)) { rtcOk = false; return; }
  if (!haveNv || resetMission) {
    missionStart = now;
    nv[0] = NVRAM_MAGIC;
    nv[1] = now >> 24; nv[2] = now >> 16; nv[3] = now >> 8; nv[4] = now;
    rtcWriteRegs(0x08, nv, 5);
    Serial.println(F("# Mission reset: met_s = 0"));
  } else {
    missionStart = ((uint32_t)nv[1] << 24) | ((uint32_t)nv[2] << 16) | ((uint32_t)nv[3] << 8) | nv[4];
  }
}

uint32_t missionSeconds() {
  uint32_t now;
  if (rtcOk && rtcNow(now)) return now >= missionStart ? now - missionStart : 0;
  return millis() / 1000UL;
}

// ============================================================================
// RFID RC522
// ============================================================================

char lastUid[21] = "";
uint32_t lastUidMs = 0, nextRfidPoll = 0, nextRfidCheck = 0;

void resetCrewState(uint32_t now);  // defined below
void printCrew(const char *id);

void sendCheckin(const char *id, const char *action) {
  Serial.print(F("{\"t\":\"evt\",\"type\":\"crew_checkin\",\"severity\":\"info\",\"crew_id\":"));
  printCrew(id);
  Serial.print(F(",\"data\":{\"action\":\""));
  Serial.print(action);
  Serial.println(F("\"}}"));
}

void rfidSetup() {
  SPI.begin();
  rfid.PCD_Init();
  delay(50);
  byte v = rfid.PCD_ReadRegister(MFRC522::VersionReg);
  Serial.print(F("# RC522 version 0x"));
  Serial.println(v, HEX);
  if (v != 0x00 && v != 0xFF) rfid.PCD_SetAntennaGain(rfid.RxGain_max);
}

void pollRfid(uint32_t now) {
  // The RC522 sometimes hangs: if it stops responding, reinitialize it
  if (due(now, nextRfidCheck, 30000)) {
    byte v = rfid.PCD_ReadRegister(MFRC522::VersionReg);
    if (v == 0x00 || v == 0xFF) {
      rfid.PCD_Init();
      rfid.PCD_SetAntennaGain(rfid.RxGain_max);
    }
  }
  if (!due(now, nextRfidPoll, 150)) return;
  if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) return;

  char uid[21];
  uint8_t n = rfid.uid.size > 10 ? 10 : rfid.uid.size;
  static const char hex[] = "0123456789ABCDEF";
  for (uint8_t i = 0; i < n; i++) {
    uid[2 * i] = hex[rfid.uid.uidByte[i] >> 4];
    uid[2 * i + 1] = hex[rfid.uid.uidByte[i] & 0x0F];
  }
  uid[2 * n] = '\0';
  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();

  if (strcmp(uid, lastUid) == 0 && now - lastUidMs < 2000) return;  // same card, bounce
  strcpy(lastUid, uid);
  lastUidMs = now;

  if (crewId[0] && strcmp(uid, crewId) == 0) {
    sendCheckin(crewId, "out");       // same card again: check out
    crewId[0] = '\0';
  } else {
    if (crewId[0]) sendCheckin(crewId, "out");  // there was another: the previous one checks out
    strcpy(crewId, uid);
    sendCheckin(crewId, "in");
  }
  resetCrewState(now);
}

// ============================================================================
// Pulse: red LED + photoresistor (A1), 50 Hz, live peak detection
// ============================================================================

TimeRing beats;
float pDc = 0, pLp = 0, pAmp = 0;
bool pInit = false, pArmed = false;
uint32_t pLastBeat = 0, pNextSample = 0;

void pulseReset() {
  beats.clear();
  pInit = false;
  pArmed = false;
  pAmp = 0;
  pLastBeat = 0;
}

void samplePulse(uint32_t now) {
  if (!due(now, pNextSample, PULSE_SAMPLE_MS)) return;
  int raw = analogRead(PIN_PULSE_LDR);
  if (!pInit) { pDc = raw; pLp = 0; pInit = true; }
  pDc += (raw - pDc) * 0.03f;           // removes the DC component (~0.7 s)
  float ac = raw - pDc;
  pLp += (ac - pLp) * 0.35f;            // low-pass filter (~3 Hz)
  float a = fabs(pLp);
  pAmp = (a > pAmp) ? a : pAmp * 0.995f; // envelope
  float thr = pAmp * 0.5f;
  if (pLp < 0) pArmed = true;
  if (pArmed && pAmp >= PULSE_MIN_AMP && pLp > thr && now - pLastBeat > PULSE_MIN_IBI_MS) {
    beats.push(now);
    pLastBeat = now;
    pArmed = false;
  }
}

// bpm = -1 if there is no measurement. quality from 0 to 1.
void computePulse(uint32_t now, int &bpm, float &quality) {
  bpm = -1;
  quality = 0;
  uint16_t iv[TimeRing::N];
  uint8_t n = 0;
  for (uint8_t i = 1; i < beats.count; i++) {
    uint32_t t0 = beats.get(i - 1), t1 = beats.get(i);
    if (now - t0 <= PULSE_WINDOW_MS && t1 - t0 < 2000) iv[n++] = t1 - t0;
  }
  if (n < 3 || now - pLastBeat > 3000) return;

  float mean = 0;
  for (uint8_t i = 0; i < n; i++) mean += iv[i];
  mean /= n;
  float var = 0;
  for (uint8_t i = 0; i < n; i++) var += (iv[i] - mean) * (iv[i] - mean);
  float cv = sqrt(var / n) / mean;

  for (uint8_t i = 1; i < n; i++) {     // median (insertion sort)
    uint16_t k = iv[i];
    int8_t j = i - 1;
    while (j >= 0 && iv[j] > k) { iv[j + 1] = iv[j]; j--; }
    iv[j + 1] = k;
  }
  float med = (n & 1) ? iv[n / 2] : (iv[n / 2 - 1] + iv[n / 2]) / 2.0f;
  float b = 60000.0f / med;
  if (b < 35 || b > 200) return;

  float expected = (PULSE_WINDOW_MS / 1000.0f) * b / 60.0f - 1.0f;   // expected intervals
  if (expected < 1) expected = 1;
  float qReg = constrain(1.0f - cv * 3.0f, 0.0f, 1.0f);              // regularity
  float qCount = constrain(n / expected, 0.0f, 1.0f);                // missed beats
  float qAmp = constrain(pAmp / (2.0f * PULSE_MIN_AMP), 0.0f, 1.0f); // signal strength
  quality = qReg * qCount * qAmp;
  bpm = (int)(b + 0.5f);
}

// ============================================================================
// HC-SR04 on the floor: push-ups
// ============================================================================

uint32_t usNext = 0;
float lastDistCm = -1;

float readDistanceCm() {
  digitalWrite(PIN_US_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_US_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_US_TRIG, LOW);
  unsigned long us = pulseIn(PIN_US_ECHO, HIGH, US_TIMEOUT_US);
  if (us == 0) return -1;   // no echo
  return us / 58.0f;
}

// --- Push-ups ---
bool puDown = false, puActive = false;
uint8_t puCnt = 0;
uint16_t puReps = 0;
uint32_t puStart = 0, puLastRep = 0;

void sendExerciseSummary() {
  float dur = (puLastRep - puStart) / 1000.0f;
  if (dur < 1) dur = 1;
  Serial.print(F("{\"t\":\"evt\",\"type\":\"exercise_summary\",\"severity\":\"info\",\"crew_id\":"));
  printCrew(crewId);
  Serial.print(F(",\"data\":{\"exercise\":\"pushup\",\"reps\":"));
  Serial.print(puReps);
  Serial.print(F(",\"duration_s\":"));
  Serial.print((uint16_t)(dur + 0.5f));
  Serial.print(F(",\"cadence_rpm\":"));
  Serial.print(puReps * 60.0f / dur, 1);
  Serial.println(F("}}"));
  puActive = false;
  puReps = 0;
}

void pushupReset() {
  puDown = false;
  puActive = false;
  puCnt = 0;
  puReps = 0;
}

void samplePushup(uint32_t now, float d) {
  float dd = (d < 0) ? 999 : d;   // no echo = nothing above = up
  if (!puDown) {
    if (dd < PUSHUP_DOWN_CM) {
      if (++puCnt >= 2) {
        puDown = true;
        puCnt = 0;
        if (!puActive) { puActive = true; puStart = now; puReps = 0; }
      }
    } else puCnt = 0;
  } else {
    if (dd > PUSHUP_UP_CM) {
      if (++puCnt >= 2) {
        puDown = false;
        puCnt = 0;
        if (!puActive) { puActive = true; puStart = now; puReps = 0; }
        puReps++;
        puLastRep = now;
#if TEST_RFID_US
        Serial.print(F("#   + push-up "));
        Serial.println(puReps);
#endif
      }
    } else puCnt = 0;
  }
}

void checkPushupEnd(uint32_t now) {
  if (!puActive) return;
  if (puReps > 0 && now - puLastRep > PUSHUP_END_MS) sendExerciseSummary();
  else if (puReps == 0 && now - puStart > 30000) puActive = false;  // went down and never came up
}

void sampleUltrasonic(uint32_t now) {
  if (!due(now, usNext, PUSHUP_SAMPLE_MS)) return;
  float d = readDistanceCm();
  lastDistCm = d;
  samplePushup(now, d);
}

// ============================================================================
// Motion: tilt switch (worn by the crew member) and inactivity
// ============================================================================

uint32_t lastMotionMs = 0;
int lastTilt = HIGH;
bool inactivitySent = false;

void sampleMotion(uint32_t now) {
  int t = digitalRead(PIN_TILT);
  if (t != lastTilt) {
    lastTilt = t;
    lastMotionMs = now;
  }
}

bool isMoving(uint32_t now) { return now - lastMotionMs < MOVING_WINDOW_MS; }
uint32_t stillForS(uint32_t now) { return isMoving(now) ? 0 : (now - lastMotionMs) / 1000UL; }

void checkInactivity(uint32_t now) {
  if (!crewId[0]) return;
  uint32_t s = stillForS(now);
  if (s == 0) {
    inactivitySent = false;
  } else if (!inactivitySent && s >= INACTIVITY_THRESHOLD_S) {
    inactivitySent = true;
    Serial.print(F("{\"t\":\"evt\",\"type\":\"inactivity\",\"severity\":\"medium\",\"crew_id\":"));
    printCrew(crewId);
    Serial.print(F(",\"data\":{\"still_for_s\":"));
    Serial.print(s);
    Serial.print(F(",\"threshold_s\":"));
    Serial.print(INACTIVITY_THRESHOLD_S);
    Serial.println(F("}}"));
  }
}

// ============================================================================
// Body temperature: NTC thermistor (A0). 5V -> NTC -> A0 -> 10k -> GND
// ============================================================================

float bodyTemp = 0, lastNtcAdc = 0;
bool bodyTempOk = false, bodyInit = false;

void sampleBodyTemp() {
  long sum = 0;
  for (uint8_t i = 0; i < 8; i++) sum += analogRead(PIN_NTC);
  float adc = sum / 8.0f;
  lastNtcAdc = adc;
  if (adc < 5 || adc > 1018) { bodyTempOk = false; bodyInit = false; return; }  // loose wire
  float r = NTC_R_FIXED * (1023.0f / adc - 1.0f);
  float lnR = log(r);
  float tC = 1.0f / (NTC_SH_A + NTC_SH_B * lnR + NTC_SH_C * lnR * lnR * lnR) - 273.15f + BODY_TEMP_OFFSET_C;
  if (!bodyInit) { bodyTemp = tC; bodyInit = true; }
  bodyTemp += (tC - bodyTemp) * 0.3f;
  bodyTempOk = bodyTemp >= BODY_TEMP_MIN_VALID && bodyTemp <= BODY_TEMP_MAX_VALID;
}

// ============================================================================
// Cabin: DHT11 (D4). Direct protocol read, no library.
// ============================================================================

float cabinT = 0, cabinH = 0;
bool cabinOk = false;
uint8_t dhtFails = 0;

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
  delay(20);                       // start signal: >18 ms low
  pinMode(PIN_DHT, INPUT_PULLUP);
  delayMicroseconds(40);
  bool ok = true;
  noInterrupts();
  // wait for the sensor to respond (low ~80 us, high ~80 us)
  if (dhtPulse(HIGH) == DHT_TIMEOUT || dhtPulse(LOW) == DHT_TIMEOUT || dhtPulse(HIGH) == DHT_TIMEOUT) ok = false;
  for (uint8_t i = 0; ok && i < 40; i++) {
    uint16_t lo = dhtPulse(LOW);   // always ~50 us
    uint16_t hi = dhtPulse(HIGH);  // ~27 us = 0, ~70 us = 1
    if (lo == DHT_TIMEOUT || hi == DHT_TIMEOUT) { ok = false; break; }
    d[i / 8] <<= 1;
    if (hi > lo) d[i / 8] |= 1;
  }
  interrupts();
  if (!ok) return false;
  if ((uint8_t)(d[0] + d[1] + d[2] + d[3]) != d[4]) return false;
  h = d[0] + d[1] * 0.1f;
  t = (d[2] & 0x7F) + d[3] * 0.1f;
  if (d[2] & 0x80) t = -t;
  return h <= 100;
}

void sampleCabin() {
  float t, h;
  if (readDHT11(t, h)) {
    cabinT = t;
    cabinH = h;
    cabinOk = true;
    dhtFails = 0;
  } else if (++dhtFails >= 5) {
    cabinOk = false;
  }
}

float dewPointC(float T, float RH) {
  if (RH < 1) RH = 1;
  float g = log(RH / 100.0f) + 17.62f * T / (243.12f + T);
  return 243.12f * g / (17.62f - g);
}

float heatIndexC(float T, float RH) {
  float F = T * 1.8f + 32;
  if (F < 80 || RH < 40) return T;   // outside the Rothfusz range
  float HI = -42.379f + 2.04901523f * F + 10.14333127f * RH - 0.22475541f * F * RH
             - 0.00683783f * F * F - 0.05481717f * RH * RH + 0.00122874f * F * F * RH
             + 0.00085282f * F * RH * RH - 0.00000199f * F * F * RH * RH;
  return (HI - 32) / 1.8f;
}

#if TEST_RFID_US
void printTest(uint32_t now) {
  Serial.print(F("# crew="));
  Serial.print(crewId[0] ? crewId : "none");
  Serial.print(F("  dist="));
  if (lastDistCm < 0) Serial.print(F("no echo"));
  else { Serial.print(lastDistCm, 1); Serial.print(F(" cm")); }
  Serial.print(F("  chest="));
  Serial.print(puDown ? F("DOWN") : F("up"));
  Serial.print(F("  reps="));
  Serial.print(puReps);
  if (puActive && puReps > 0) {
    uint32_t left = PUSHUP_END_MS - (now - puLastRep);
    Serial.print(F("  (summary in "));
    Serial.print(left / 1000 + 1);
    Serial.print(F(" s)"));
  }
  Serial.println();
}
#endif

// ============================================================================
// Telemetry
// ============================================================================

void printCrew(const char *id) {
  if (id && id[0]) {
    Serial.print('"');
    Serial.print(id);
    Serial.print('"');
  } else {
    Serial.print(F("null"));
  }
}

void resetCrewState(uint32_t now) {
  pulseReset();
  if (puActive && puReps > 0) sendExerciseSummary();
  pushupReset();
  lastMotionMs = now;   // the card was just scanned: they moved
  inactivitySent = false;
}

bool firstAlert;
void alert(const __FlashStringHelper *code) {
  if (!firstAlert) Serial.print(',');
  firstAlert = false;
  Serial.print('"');
  Serial.print(code);
  Serial.print('"');
}

void sendTelemetry(uint32_t now) {
  int bpm;
  float q;
  computePulse(now, bpm, q);
  bool hrOk = bpm > 0 && q >= HR_QUALITY_MIN;
  bool moving = isMoving(now);

  float dew = 0, hi = 0;
  const char *risk = "low";
  if (cabinOk) {
    dew = dewPointC(cabinT, cabinH);
    hi = heatIndexC(cabinT, cabinH);
    float margin = cabinT - dew;
    risk = margin > 5 ? "low" : (margin >= 2 ? "medium" : "high");
  }

  Serial.print(F("{\"t\":\"tel\",\"met_s\":"));
  Serial.print(missionSeconds());
  Serial.print(F(",\"crew_id\":"));
  printCrew(crewId);

  Serial.print(F(",\"vitals\":{\"heart_rate_bpm\":"));
  if (hrOk) Serial.print(bpm); else Serial.print(F("null"));
  Serial.print(F(",\"hr_quality\":"));
  Serial.print(q, 2);
  Serial.print(F(",\"resp_rate_bpm\":null,\"body_temp_c\":"));   // breathing is not measured
  if (bodyTempOk) Serial.print(bodyTemp, 1); else Serial.print(F("null"));

  Serial.print(F("},\"motion\":{\"activity\":\""));
  Serial.print(moving ? F("moving") : F("still"));
  Serial.print(F("\",\"still_for_s\":"));
  Serial.print(stillForS(now));

  Serial.print(F("},\"cabin\":{\"temp_c\":"));
  if (cabinOk) {
    Serial.print(cabinT, 1);
    Serial.print(F(",\"humidity_pct\":"));
    Serial.print((int)(cabinH + 0.5f));
    Serial.print(F(",\"dew_point_c\":"));
    Serial.print(dew, 1);
    Serial.print(F(",\"heat_index_c\":"));
    Serial.print(hi, 1);
    Serial.print(F(",\"condensation_risk\":\""));
    Serial.print(risk);
    Serial.print('"');
  } else {
    Serial.print(F("null,\"humidity_pct\":null,\"dew_point_c\":null,\"heat_index_c\":null,\"condensation_risk\":null"));
  }

  Serial.print(F("},\"alerts\":["));
  firstAlert = true;
  if (hrOk && bpm > ALERT_HR_HIGH) alert(F("HR_HIGH"));
  if (hrOk && bpm < ALERT_HR_LOW) alert(F("HR_LOW"));
  if (bodyTempOk && bodyTemp > ALERT_BODY_TEMP_HIGH) alert(F("BODY_TEMP_HIGH"));
  if (bodyTempOk && bodyTemp < ALERT_BODY_TEMP_LOW) alert(F("BODY_TEMP_LOW"));
  if (cabinOk && cabinT > ALERT_CABIN_TEMP_HIGH) alert(F("CABIN_TEMP_HIGH"));
  if (cabinOk && cabinT < ALERT_CABIN_TEMP_LOW) alert(F("CABIN_TEMP_LOW"));
  if (cabinOk && hi > ALERT_HEAT_INDEX_HIGH) alert(F("HEAT_INDEX_HIGH"));
  if (cabinOk && risk[0] == 'h') alert(F("CONDENSATION_HIGH"));
  Serial.println(F("]}"));
}

#if DEBUG_SENSORS
void printDebug(uint32_t now) {
  Serial.print(F("# dbg hr_amp="));
  Serial.print(pAmp, 1);
  Serial.print(F(" beats="));
  Serial.print(beats.count);
  Serial.print(F(" dist_cm="));
  Serial.print(lastDistCm, 1);
  Serial.print(F(" reps="));
  Serial.print(puReps);
  Serial.print(F(" ntc_adc="));
  Serial.print(lastNtcAdc, 0);
  Serial.print(F(" body_c="));
  Serial.print(bodyTemp, 1);
  Serial.print(F(" tilt="));
  Serial.print(lastTilt);
  Serial.print(F(" still_s="));
  Serial.println(stillForS(now));
}
#endif

// ============================================================================
// setup / loop
// ============================================================================

uint32_t nextSecond = 0, nextDht = 0, nextTelemetry = 0;

void setup() {
  Serial.begin(SERIAL_BAUD);
  pinMode(PIN_TILT, INPUT_PULLUP);
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  pinMode(PIN_US_TRIG, OUTPUT);
  pinMode(PIN_US_ECHO, INPUT);
  pinMode(PIN_PULSE_LED, OUTPUT);
  pinMode(PIN_DHT, INPUT_PULLUP);
  digitalWrite(PIN_PULSE_LED, HIGH);   // the pulse LED is always on

  Serial.println(F("# AstroMed UNO starting"));
  delay(50);
  bool resetMission = digitalRead(PIN_BUTTON) == LOW;
  rtcSetup(resetMission);
  rfidSetup();

  lastTilt = digitalRead(PIN_TILT);
  uint32_t now = millis();
  lastMotionMs = now;
  nextDht = now + 1500;                 // the DHT11 needs ~1 s after power-up
  nextTelemetry = now + TELEMETRY_PERIOD_MS;
  Serial.println(F("# ready. Scan a card to start."));
#if TEST_RFID_US
  Serial.println(F("# TEST: RC522 + HC-SR04 only (push-ups)."));
#endif
}

void loop() {
  uint32_t now = millis();

  sampleUltrasonic(now);
  pollRfid(now);
  checkPushupEnd(now);

#if TEST_RFID_US
  if (due(now, nextSecond, 1000)) printTest(now);
  return;
#endif

  samplePulse(now);
  sampleMotion(now);

  if (due(now, nextSecond, 1000)) {
    sampleBodyTemp();
    checkInactivity(now);
#if DEBUG_SENSORS
    printDebug(now);
#endif
  }
  if (due(now, nextDht, 2500)) sampleCabin();
  if (due(now, nextTelemetry, TELEMETRY_PERIOD_MS)) sendTelemetry(now);
}
