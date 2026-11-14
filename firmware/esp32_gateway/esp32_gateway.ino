// SpaceHealth - firmware del ESP32 (pasarela WiFi)
//
// Lee del UNO (UART2, GPIO16, 115200) una linea JSON por mensaje:
//   {"t":"tel", ...}  -> POST {API_BASE}/api/v1/telemetry
//   {"t":"evt", ...}  -> POST {API_BASE}/api/v1/events
// Le pone device_id y ts (UTC, ISO 8601, hora por NTP), y lo manda con
// Content-Type: application/json y X-API-Key.
//
// Si el backend no responde 200 con {"ok": true}, reintenta (1 s, 2 s, 4 s ... 30 s)
// y guarda hasta 50 mensajes en cola; si se llena, descarta el mas antiguo.
// El ts de cada mensaje se fija al recibirlo del UNO y no cambia en los reintentos,
// asi el backend puede descartar duplicados por (device_id, ts, type).
//
// Si no hay Internet para NTP, toma la hora de la cabecera Date del backend.
//
// Placa: "ESP32 Dev Module" (core esp32 de Espressif). Libreria: ArduinoJson 7.
// Monitor serie del ESP32 a 115200 para ver el estado.

#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>
#include <time.h>
#include <sys/time.h>
#include "config.h"

HardwareSerial UnoSerial(2);

// ============================================================================
// Cola de mensajes
// ============================================================================

enum Kind : uint8_t { K_TELEMETRY = 0, K_CHECKIN, K_INACTIVITY, K_EXERCISE, K_OTHER, K_COUNT };

struct Msg {
  Kind kind;
  String raw;        // linea tal cual llego del UNO
  time_t epoch;      // 0 = aun sin hora
  uint32_t capMs;    // millis() al recibirlo
};

Msg msgQueue[QUEUE_MAX];
uint8_t qHead = 0, qCount = 0;
time_t lastEpochByKind[K_COUNT] = {0};

uint32_t nextTryMs = 0, retryDelay = RETRY_MIN_MS;
uint32_t sentOk = 0, sendFail = 0, dropped = 0;
uint32_t ledOffMs = 0;

bool timeSynced() { return time(nullptr) > 1700000000; }

// Pone hora a los mensajes que aun no la tienen, en orden de llegada.
// Si dos mensajes del mismo tipo caerian en el mismo segundo (p. ej. "out" e "in"
// al cambiar de tarjeta), el segundo se adelanta 1 s para que el backend no
// lo tome por duplicado.
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
    Serial.println(F("[cola] llena: descarto el mensaje mas antiguo"));
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
// Construccion del JSON final
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

// Si no hay NTP (red sin Internet), usa la cabecera Date de cualquier respuesta del backend
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
  time_t t = mktime(&tm);              // la zona horaria es UTC (configTime(0, 0, ...))
  if (t < 1700000000) return false;
  struct timeval tv = {t, 0};
  settimeofday(&tv, nullptr);
  Serial.printf("[hora] tomada del backend: %s\n", isoUtc(t).c_str());
  return true;
}

void processQueue() {
  if (qCount == 0 || WiFi.status() != WL_CONNECTED) return;
  if ((int32_t)(millis() - nextTryMs) < 0) return;
  Msg &m = msgQueue[qHead];
  if (m.epoch == 0) return;   // esperando hora

  String body;
  if (!buildBody(m, body)) {
    Serial.println(F("[envio] JSON del UNO invalido, descartado"));
    dequeue();
    return;
  }
  const char *path = (m.kind == K_TELEMETRY) ? "/api/v1/telemetry" : "/api/v1/events";
  String resp;
  int code = postJson(path, body, resp);

  bool ok = false;
  if (code >= 200 && code < 300) {
    JsonDocument r;
    // Se espera {"ok": true}; si la respuesta no es JSON, con el 2xx basta
    ok = deserializeJson(r, resp) || r["ok"].isNull() || r["ok"].as<bool>();
  } else if (code == 409) {
    ok = true;  // el backend ya lo tenia (duplicado)
  }

  if (ok) {
    Serial.printf("[envio] %s %d (%u en cola)\n", path, code, qCount - 1);
    dequeue();
    sentOk++;
    retryDelay = RETRY_MIN_MS;
    nextTryMs = millis();
    digitalWrite(STATUS_LED_PIN, HIGH);
    ledOffMs = millis() + 60;
  } else if (code >= 400 && code < 500 && code != 408 && code != 429) {
    // Error del cliente (422 valor imposible, 401 clave mala...): reintentar no lo arregla
    Serial.printf("[envio] %s rechazado %d: %s\n  cuerpo: %s\n", path, code, resp.c_str(), body.c_str());
    dequeue();
    sendFail++;
  } else {
    sendFail++;
    Serial.printf("[envio] %s fallo (%d), reintento en %u ms\n", path, code, retryDelay);
    nextTryMs = millis() + retryDelay;
    retryDelay = min<uint32_t>(retryDelay * 2, RETRY_MAX_MS);
  }
}

// ============================================================================
// Lectura del UNO
// ============================================================================

String lineBuf;
bool lineOverflow = false;
const size_t MAX_LINE = 1024;

void handleLine(String &line) {
  line.trim();
  if (line.length() == 0) return;
  if (line[0] != '{') {                 // depuracion del UNO ("# ...")
    Serial.print(F("[uno] "));
    Serial.println(line);
    return;
  }
  JsonDocument doc;
  if (deserializeJson(doc, line)) {
    Serial.print(F("[uno] linea JSON corrupta: "));
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
    Serial.printf("[uno] evento %s\n", type);
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
// WiFi y estado
// ============================================================================

uint32_t lastWifiAttempt = 0, wifiUpSince = 0, lastHttpTimeTry = 0, lastStatus = 0;
bool wasConnected = false;

void maintainWifi() {
  bool up = WiFi.status() == WL_CONNECTED;
  if (up && !wasConnected) {
    wifiUpSince = millis();
    Serial.printf("[wifi] conectado, IP %s\n", WiFi.localIP().toString().c_str());
  }
  if (!up && wasConnected) Serial.println(F("[wifi] desconectado"));
  wasConnected = up;

  if (!up && millis() - lastWifiAttempt > 10000) {
    lastWifiAttempt = millis();
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASS);
  }
  // Sin NTP a los 15 s de tener WiFi: probar con la hora del backend cada 30 s
  if (up && !timeSynced() && millis() - wifiUpSince > 15000 && millis() - lastHttpTimeTry > 30000) {
    lastHttpTimeTry = millis();
    syncTimeFromBackend();
  }
}

void printStatus() {
  if (millis() - lastStatus < 30000) return;
  lastStatus = millis();
  Serial.printf("[estado] wifi=%s hora=%s cola=%u enviados=%lu fallos=%lu descartados=%lu\n",
                WiFi.status() == WL_CONNECTED ? "si" : "no",
                timeSynced() ? isoUtc(time(nullptr)).c_str() : "sin sincronizar",
                qCount, (unsigned long)sentOk, (unsigned long)sendFail, (unsigned long)dropped);
}

// ============================================================================
// setup / loop
// ============================================================================

void setup() {
  Serial.begin(115200);
  pinMode(STATUS_LED_PIN, OUTPUT);
  digitalWrite(STATUS_LED_PIN, LOW);

  UnoSerial.setRxBufferSize(4096);   // aguanta varios mensajes mientras se hace un POST
  UnoSerial.begin(UNO_BAUD, SERIAL_8N1, UNO_RX_PIN, UNO_TX_PIN);
  lineBuf.reserve(MAX_LINE);

  Serial.println(F("\nSpaceHealth ESP32 arrancando"));
  WiFi.mode(WIFI_STA);
  WiFi.onEvent([](WiFiEvent_t, WiFiEventInfo_t info) {
    uint8_t r = info.wifi_sta_disconnected.reason;
    if (r == 36) return;  // STA_LEAVING: lo provoca nuestro propio reintento, no es un error
    Serial.printf("[wifi] no conecta a \"%s\": motivo %u (%s)\n", WIFI_SSID, r,
                  WiFi.disconnectReasonName((wifi_err_reason_t)r));
    if (r == WIFI_REASON_NO_AP_FOUND)
      Serial.println(F("       No ve la red: el ESP32 solo usa 2,4 GHz. Pon el punto de acceso en 2,4 GHz y revisa el nombre."));
    else if (r == WIFI_REASON_AUTH_FAIL || r == WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT || r == WIFI_REASON_HANDSHAKE_TIMEOUT)
      Serial.println(F("       Ve la red pero no entra: revisa la contrasena (o pon la seguridad en WPA2)."));
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
