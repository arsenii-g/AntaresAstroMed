// AstroMed - ESP32 configuration
// Copy this file as config.h and fill it in. config.h is not committed to git (it holds keys).
#pragma once

#define WIFI_SSID     "YOUR_WIFI_2_4GHZ"     // the ESP32 only works on 2.4 GHz
#define WIFI_PASS     "YOUR_WIFI_PASSWORD"

// No trailing slash. http://IP:port on the local network, or https://... (the certificate is not verified)
#define API_BASE      "https://BACKEND_IP:8000"
#define API_KEY       "YOUR_API_KEY"
#define DEVICE_ID     "esp32-01"

#define NTP_SERVER_1  "pool.ntp.org"
#define NTP_SERVER_2  "time.google.com"

// ESP32 UART2: RX = GPIO16 (the UNO TX arrives through the 1k/2k divider)
#define UNO_RX_PIN    16
#define UNO_TX_PIN    17     // not used (no need to wire it)
#define UNO_BAUD      115200

#define QUEUE_MAX        50     // messages kept if the backend does not answer
#define HTTP_TIMEOUT_MS  4000
#define RETRY_MIN_MS     1000   // retries: 1 s, 2 s, 4 s ... up to 30 s
#define RETRY_MAX_MS     30000
#define STATUS_LED_PIN   2      // board's blue LED: blinks on every successful send
