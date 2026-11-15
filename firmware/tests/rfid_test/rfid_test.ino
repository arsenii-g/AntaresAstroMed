// RC522 RFID reader test with Arduino UNO
// Library: "MFRC522" (GithubCommunity), from the Library Manager.
// Serial Monitor at 115200 baud.
//
// Wiring:
//   RC522  -> UNO
//   SDA    -> D10
//   SCK    -> D13
//   MOSI   -> D11
//   MISO   -> D12
//   IRQ    -> not connected
//   GND    -> GND
//   RST    -> D9
//   3.3V   -> 3.3V   (NEVER to 5V)

#include <SPI.h>
#include <MFRC522.h>

const byte PIN_SS  = 10;
const byte PIN_RST = 9;
MFRC522 rfid(PIN_SS, PIN_RST);

// Crew members seen during the test, to alternate check-in and check-out
const byte MAX_CREW = 5;
String crewIds[MAX_CREW];
bool   crewIn[MAX_CREW];
byte   crewCount = 0;

// Avoids repeated reads of the same card
String lastUid = "";
unsigned long lastReadMs = 0;
const unsigned long REPEAT_MS = 2000;

String uidToHex(const MFRC522::Uid &uid) {
  String s;
  for (byte i = 0; i < uid.size; i++) {
    if (uid.uidByte[i] < 0x10) s += '0';
    s += String(uid.uidByte[i], HEX);
  }
  s.toUpperCase();
  return s;
}

int findOrAdd(const String &uid) {
  for (byte i = 0; i < crewCount; i++) {
    if (crewIds[i] == uid) return i;
  }
  if (crewCount < MAX_CREW) {
    crewIds[crewCount] = uid;
    crewIn[crewCount] = false;
    return crewCount++;
  }
  return -1;
}

void setup() {
  Serial.begin(115200);
  SPI.begin();
  rfid.PCD_Init();
  delay(50);

  byte version = rfid.PCD_ReadRegister(MFRC522::VersionReg);
  Serial.print(F("RC522 version: 0x"));
  Serial.println(version, HEX);

  if (version == 0x00 || version == 0xFF) {
    Serial.println(F("ERROR: RC522 not detected. Check wires, solder joints and 3.3V."));
  } else {
    rfid.PCD_SetAntennaGain(rfid.RxGain_max);  // maximum read sensitivity
    Serial.println(F("RC522 OK. Bring a card or key fob closer (within 3 cm)."));
  }
}

unsigned long lastBeatMs = 0;

void loop() {
  // Heartbeat: confirms the program is still running
  if (millis() - lastBeatMs > 3000) {
    lastBeatMs = millis();
    Serial.println(F("... waiting for a card"));
  }

  if (!rfid.PICC_IsNewCardPresent()) return;
  if (!rfid.PICC_ReadCardSerial()) return;

  String uid = uidToHex(rfid.uid);
  unsigned long now = millis();

  if (uid == lastUid && now - lastReadMs < REPEAT_MS) {
    rfid.PICC_HaltA();
    rfid.PCD_StopCrypto1();
    return;
  }
  lastUid = uid;
  lastReadMs = now;

  MFRC522::PICC_Type type = rfid.PICC_GetType(rfid.uid.sak);
  Serial.print(F("Card: "));
  Serial.print(uid);
  Serial.print(F("   type: "));
  Serial.println(rfid.PICC_GetTypeName(type));

  const char *action = "in";
  int idx = findOrAdd(uid);
  if (idx >= 0) {
    crewIn[idx] = !crewIn[idx];
    action = crewIn[idx] ? "in" : "out";
  } else {
    Serial.println(F("Warning: crew list full, state not saved."));
  }

  // Same format as the crew_checkin event in the doc
  Serial.print(F("{\"type\":\"crew_checkin\",\"crew_id\":\""));
  Serial.print(uid);
  Serial.print(F("\",\"data\":{\"action\":\""));
  Serial.print(action);
  Serial.println(F("\"}}"));
  Serial.println();

  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
}
