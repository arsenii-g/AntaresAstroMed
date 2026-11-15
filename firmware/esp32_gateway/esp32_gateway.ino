// AstroMed - ESP32 firmware (WiFi gateway)
//
// Reads one JSON line per message from the UNO (UART2, GPIO16, 115200):
//   {"t":"tel", ...}  -> POST {API_BASE}/api/v1/telemetry
//   {"t":"evt", ...}  -> POST {API_BASE}/api/v1/events
// Adds device_id and ts (UTC, ISO 8601, time from NTP) and sends it with
// Content-Type: application/json and X-API-Key.
//
// If the backend does not answer 200 with {"ok": true}, it retries (1 s, 2 s, 4 s ... 30 s)
// and keeps up to 50 messages queued; if the queue fills up, it drops the oldest.
// Each message's ts is fixed when it arrives from the UNO and does not change on retries,
// so the backend can discard duplicates by (device_id, ts, type).
//
// If there is no Internet for NTP, it takes the time from the backend's Date header.
//
// Board: "ESP32 Dev Module" (Espressif esp32 core). Library: ArduinoJson 7.
// Open the ESP32 serial monitor at 115200 to see the status.

#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>
#include <time.h>
#include <sys/time.h>
#include "config.h"

HardwareSerial UnoSerial(2);

// ============================================================================
// Message queue
// ============================================================================

enum Kind : uint8_t { K_TELEMETRY = 0, K_CHECKIN, K_INACTIVITY, K_EXERCISE, K_OTHER, K_COUNT };

struct Msg {
  Kind kind;
  String raw;        // line exactly as received from the UNO
  time_t epoch;      // 0 = no time yet
  uint32_t capMs;    // millis() when received
};

Msg msgQueue[QUEUE_MAX];
uint8_t qHead = 0, qCount = 0;
time_t lastEpochByKind[K_COUNT] = {0};

uint32_t nextTryMs = 0, retryDelay = RETRY_MIN_MS;
uint32_t sentOk = 0, sendFail = 0, dropped = 0;
uint32_t ledOffMs = 0;

bool timeSynced() { return time(nullptr) > 1700000000; }

// Timestamps messages that do not have a time yet, in arrival order.
// If two messages of the same type would fall in the same second (e.g. "out" and "in"
// when swapping cards), the second is moved ahead by 1 s so the backend does not
// treat it as a duplicate.
void resolveTimes() {
  if (!timeSynced()) return;
  time_t nowE = time(nullptr);
  uint32_t nowMs = millis();
  for (uint8_t i = 0; i < qCount; i++) {
    Msg &m = msgQueue[(qHead + i) % QUEUE_MAX];
    if (m.epoch != 0) continue;
    time_t e = nowE - (time_t)((nowMs - m.capMs) / 1000UL);
    if (e <= lastEpochByKind[m.kind]) e = lastEpochByKind[m.kind] + 1;
    lastEpochByKind[m.kind] = e;
    m.epoch = e;
  }
}

void enqueue(Kind kind, const String &line) {
  if (qCount == QUEUE_MAX) {
    msgQueue[qHead].raw = String();
    qHead = (qHead + 1) % QUEUE_MAX;
    qCount--;
    dropped++;
    Serial.println(F("[queue] full: dropping the oldest message"));
  }
  Msg &m = msgQueue[(qHead + qCount) % QUEUE_MAX];
  m.kind = kind;
  m.raw = line;
  m.epoch = 0;
  m.capMs = millis();
  qCount++;
  resolveTimes();
}

void dequeue() {
  msgQueue[qHead].raw = String();
  qHead = (qHead + 1) % QUEUE_MAX;
  qCount--;
}

// ============================================================================
// Building the final JSON
// ============================================================================

String isoUtc(time_t t) {
  struct tm tm;
  gmtime_r(&t, &tm);
  char b[24];
  strftime(b, sizeof b, "%Y-%m-%dT%H:%M:%SZ", &tm);
  return String(b);
}

static void copyOrNull(JsonDocument &dst, const char *key, JsonVariantConst v) {
  if (v.isNull()) dst[key] = nullptr;
  else dst[key] = v;
}

bool buildBody(const Msg &m, String &out) {
  JsonDocument in;
  if (deserializeJson(in, m.raw)) return false;
  JsonDocument doc;
  doc["device_id"] = DEVICE_ID;
  doc["ts"] = isoUtc(m.epoch);
  if (m.kind == K_TELEMETRY) {
    doc["met_s"] = in["met_s"];
    copyOrNull(doc, "crew_id", in["crew_id"]);
    doc["vitals"] = in["vitals"];
    doc["motion"] = in["motion"];
    doc["cabin"] = in["cabin"];
    if (in["alerts"].is<JsonArrayConst>()) doc["alerts"] = in["alerts"];
    else doc["alerts"].to<JsonArray>();
  } else {
    copyOrNull(doc, "crew_id", in["crew_id"]);
    doc["type"] = in["type"];
    doc["severity"] = in["severity"];
    if (in["data"].is<JsonObjectConst>()) doc["data"] = in["data"];
    else doc["data"].to<JsonObject>();
  }
  out = "";
  serializeJson(doc, out);
  return true;
}

// ============================================================================
// HTTP
// ============================================================================

WiFiClient plainClient;
WiFiClientSecure secureClient;

bool beginHttp(HTTPClient &http, const String &url) {
  http.setTimeout(HTTP_TIMEOUT_MS);
  http.setConnectTimeout(HTTP_TIMEOUT_MS);
  if (url.startsWith("https")) {
    secureClient.setInsecure();
    return http.begin(secureClient, url);
  }
  return http.begin(plainClient, url);
}

int postJson(const char *path, const String &body, String &resp) {
  HTTPClient http;
  if (!beginHttp(http, String(API_BASE) + path)) return -1;
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-API-Key", API_KEY);
  int code = http.POST(body);
  resp = (code > 0) ? http.getString() : String();
  http.end();
  return code;
}

// If there is no NTP (network without Internet), use the Date header of any backend response
bool syncTimeFromBackend() {
  HTTPClient http;
  if (!beginHttp(http, String(API_BASE) + "/")) return false;
  const char *hdrs[] = {"Date"};
  http.collectHeaders(hdrs, 1);
  int code = http.GET();
  String date = http.header("Date");   // "Sat, 14 Nov 2026 10:30:05 GMT"
  http.end();
  if (code <= 0 || date.length() < 25) return false;

  int day, year, h, mi, s;
  char mon[4];
  if (sscanf(date.c_str(), "%*3s, %d %3s %d %d:%d:%d", &day, mon, &year, &h, &mi, &s) != 6) return false;
  static const char *months = "JanFebMarAprMayJunJulAugSepOctNovDec";
  const char *p = strstr(months, mon);
  if (!p) return false;
  struct tm tm = {};
  tm.tm_year = year - 1900;
  tm.tm_mon = (p - months) / 3;
  tm.tm_mday = day;
  tm.tm_hour = h;
  tm.tm_min = mi;
  tm.tm_sec = s;
  time_t t = mktime(&tm);              // the time zone is UTC (configTime(0, 0, ...))
  if (t < 1700000000) return false;
  struct timeval tv = {t, 0};
  settimeofday(&tv, nullptr);
  Serial.printf("[time] taken from backend: %s\n", isoUtc(t).c_str());
  return true;
}

void processQueue() {
  if (qCount == 0 || WiFi.status() != WL_CONNECTED) return;
  if ((int32_t)(millis() - nextTryMs) < 0) return;
  Msg &m = msgQueue[qHead];
  if (m.epoch == 0) return;   // waiting for time

  String body;
  if (!buildBody(m, body)) {
    Serial.println(F("[send] invalid JSON from UNO, dropped"));
    dequeue();
    return;
  }
  const char *path = (m.kind == K_TELEMETRY) ? "/api/v1/telemetry" : "/api/v1/events";
  String resp;
  int code = postJson(path, body, resp);

  bool ok = false;
  if (code >= 200 && code < 300) {
    JsonDocument r;
    // {"ok": true} is expected; if the response is not JSON, a 2xx is enough
    ok = deserializeJson(r, resp) || r["ok"].isNull() || r["ok"].as<bool>();
  } else if (code == 409) {
    ok = true;  // the backend already had it (duplicate)
  }

  if (ok) {
    Serial.printf("[send] %s %d (%u queued)\n", path, code, qCount - 1);
    dequeue();
    sentOk++;
    retryDelay = RETRY_MIN_MS;
    nextTryMs = millis();
    digitalWrite(STATUS_LED_PIN, HIGH);
    ledOffMs = millis() + 60;
  } else if (code >= 400 && code < 500 && code != 401 && code != 403 && code != 408 && code != 429) {
    // Client error (422 impossible value...): retrying will not fix it.
    // 401/403 (bad key) are retried: once the key is fixed, no data is lost
    Serial.printf("[send] %s rejected %d: %s\n  body: %s\n", path, code, resp.c_str(), body.c_str());
    dequeue();
    sendFail++;
  } else {
    sendFail++;
    Serial.printf("[send] %s failed (%d), retrying in %u ms\n", path, code, retryDelay);
    if (code < 0) probeBackend();
    if (code >= 500 && retryDelay == RETRY_MIN_MS) {   // only on the first failure of each message
      Serial.printf("  response: %.300s\n  body: %s\n", resp.c_str(), body.c_str());
    }
    nextTryMs = millis() + retryDelay;
    retryDelay = min<uint32_t>(retryDelay * 2, RETRY_MAX_MS);
  }
}

// Diagnostics when there is no connection: opens a bare TCP connection to the backend
// and measures how long it takes to fail. At most once per minute.
void probeBackend() {
  static uint32_t lastProbe = 0;
  if (lastProbe && millis() - lastProbe < 60000) return;
  lastProbe = millis();
  String base = API_BASE;
  int s = base.indexOf("://");
  String hostPort = base.substring(s < 0 ? 0 : s + 3);
  int slash = hostPort.indexOf('/');
  if (slash >= 0) hostPort = hostPort.substring(0, slash);
  int colon = hostPort.indexOf(':');
  String host = colon >= 0 ? hostPort.substring(0, colon) : hostPort;
  uint16_t port = colon >= 0 ? hostPort.substring(colon + 1).toInt() : (base.startsWith("https") ? 443 : 80);

  WiFiClient c;
  uint32_t t0 = millis();
  bool ok = c.connect(host.c_str(), port, HTTP_TIMEOUT_MS);
  uint32_t dt = millis() - t0;
  c.stop();
  Serial.printf("[diag] my IP %s, gateway %s. TCP to %s:%u: %s in %lu ms\n",
                WiFi.localIP().toString().c_str(), WiFi.gatewayIP().toString().c_str(),
                host.c_str(), port, ok ? "CONNECTS" : "fails", (unsigned long)dt);
  if (ok)
    Serial.println(F("[diag] The port is open: the problem is the protocol (http/https) or the server."));
  else if (dt < HTTP_TIMEOUT_MS - 500)
    Serial.println(F("[diag] Fails instantly: the computer answers but no server is on that port (not started, or listening only on 127.0.0.1)."));
  else
    Serial.println(F("[diag] Times out: packets are not arriving (firewall, wrong IP, or the hotspot isolates clients)."));
}

// ============================================================================
// Reading from the UNO
// ============================================================================

String lineBuf;
bool lineOverflow = false;
const size_t MAX_LINE = 1024;

void handleLine(String &line) {
  line.trim();
  if (line.length() == 0) return;
  if (line[0] != '{') {                 // UNO debug output ("# ...")
    Serial.print(F("[uno] "));
    Serial.println(line);
    return;
  }
  JsonDocument doc;
  if (deserializeJson(doc, line)) {
    Serial.print(F("[uno] corrupt JSON line: "));
    Serial.println(line);
    return;
  }
  const char *t = doc["t"] | "";
  if (strcmp(t, "tel") == 0) {
    enqueue(K_TELEMETRY, line);
  } else if (strcmp(t, "evt") == 0) {
    const char *type = doc["type"] | "";
    Kind k = K_OTHER;
    if (strcmp(type, "crew_checkin") == 0) k = K_CHECKIN;
    else if (strcmp(type, "inactivity") == 0) k = K_INACTIVITY;
    else if (strcmp(type, "exercise_summary") == 0) k = K_EXERCISE;
    Serial.printf("[uno] event %s\n", type);
    enqueue(k, line);
  }
}

void readUno() {
  while (UnoSerial.available()) {
    char c = (char)UnoSerial.read();
    if (c == '\n') {
      if (!lineOverflow) handleLine(lineBuf);
      lineBuf = "";
      lineOverflow = false;
    } else if (c != '\r') {
      if (lineBuf.length() < MAX_LINE) lineBuf += c;
      else lineOverflow = true;
    }
  }
}

// ============================================================================
// WiFi and status
// ============================================================================

uint32_t lastWifiAttempt = 0, wifiUpSince = 0, lastHttpTimeTry = 0, lastStatus = 0;
bool wasConnected = false;

void maintainWifi() {
  bool up = WiFi.status() == WL_CONNECTED;
  if (up && !wasConnected) {
    wifiUpSince = millis();
    Serial.printf("[wifi] connected, IP %s\n", WiFi.localIP().toString().c_str());
  }
  if (!up && wasConnected) Serial.println(F("[wifi] disconnected"));
  wasConnected = up;

  if (!up && millis() - lastWifiAttempt > 10000) {
    lastWifiAttempt = millis();
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASS);
  }
  // No NTP 15 s after WiFi is up: try the backend's time every 30 s
  if (up && !timeSynced() && millis() - wifiUpSince > 15000 && millis() - lastHttpTimeTry > 30000) {
    lastHttpTimeTry = millis();
    syncTimeFromBackend();
  }
}

void printStatus() {
  if (millis() - lastStatus < 30000) return;
  lastStatus = millis();
  Serial.printf("[status] wifi=%s time=%s queue=%u sent=%lu failures=%lu dropped=%lu\n",
                WiFi.status() == WL_CONNECTED ? "yes" : "no",
                timeSynced() ? isoUtc(time(nullptr)).c_str() : "not synced",
                qCount, (unsigned long)sentOk, (unsigned long)sendFail, (unsigned long)dropped);
}

// ============================================================================
// setup / loop
// ============================================================================

void setup() {
  Serial.begin(115200);
  pinMode(STATUS_LED_PIN, OUTPUT);
  digitalWrite(STATUS_LED_PIN, LOW);

  UnoSerial.setRxBufferSize(4096);   // holds several messages while a POST is in progress
  UnoSerial.begin(UNO_BAUD, SERIAL_8N1, UNO_RX_PIN, UNO_TX_PIN);
  lineBuf.reserve(MAX_LINE);

  Serial.println(F("\nAstroMed ESP32 starting"));
  WiFi.mode(WIFI_STA);
  WiFi.onEvent([](WiFiEvent_t, WiFiEventInfo_t info) {
    uint8_t r = info.wifi_sta_disconnected.reason;
    if (r == 36) return;  // STA_LEAVING: caused by our own retry, not an error
    Serial.printf("[wifi] cannot connect to \"%s\": reason %u (%s)\n", WIFI_SSID, r,
                  WiFi.disconnectReasonName((wifi_err_reason_t)r));
    if (r == WIFI_REASON_NO_AP_FOUND)
      Serial.println(F("       Cannot see the network: the ESP32 only uses 2.4 GHz. Set the access point to 2.4 GHz and check the name."));
    else if (r == WIFI_REASON_AUTH_FAIL || r == WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT || r == WIFI_REASON_HANDSHAKE_TIMEOUT)
      Serial.println(F("       Sees the network but cannot join: check the password (or set security to WPA2)."));
  }, ARDUINO_EVENT_WIFI_STA_DISCONNECTED);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  lastWifiAttempt = millis();
  configTime(0, 0, NTP_SERVER_1, NTP_SERVER_2);   // UTC
}

void loop() {
  readUno();
  maintainWifi();
  resolveTimes();
  processQueue();
  readUno();
  if (ledOffMs && (int32_t)(millis() - ledOffMs) >= 0) {
    digitalWrite(STATUS_LED_PIN, LOW);
    ledOffMs = 0;
  }
  printStatus();
}
