// SpaceHealth - configuracion del ESP32
// Copia este archivo como config.h y rellenalo. config.h no se sube a git (tiene claves).
#pragma once

#define WIFI_SSID     "TU_WIFI_2_4GHZ"     // el ESP32 solo funciona en 2,4 GHz
#define WIFI_PASS     "TU_CLAVE_WIFI"

// Sin barra final. http://IP:puerto en la red local, o https://... (no se verifica el certificado)
#define API_BASE      "https://IP_DEL_BACKEND:8000"
#define API_KEY       "TU_API_KEY"
#define DEVICE_ID     "esp32-01"

#define NTP_SERVER_1  "pool.ntp.org"
#define NTP_SERVER_2  "time.google.com"

// UART2 del ESP32: RX = GPIO16 (llega el TX del UNO por el divisor 1k/2k)
#define UNO_RX_PIN    16
#define UNO_TX_PIN    17     // no se usa (no hace falta cablearlo)
#define UNO_BAUD      115200

#define QUEUE_MAX        50     // mensajes guardados si el backend no responde
#define HTTP_TIMEOUT_MS  4000
#define RETRY_MIN_MS     1000   // reintentos: 1 s, 2 s, 4 s ... hasta 30 s
#define RETRY_MAX_MS     30000
#define STATUS_LED_PIN   2      // LED azul de la placa: parpadea en cada envio correcto
