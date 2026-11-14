# Hardware: PCB

Aquí va el diseño de la placa (PCB) que sustituye a la protoboard del UNO y del ESP32.

## Qué subir

| Carpeta o archivo | Qué |
|---|---|
| `kicad/` (o el programa que uses) | Proyecto fuente: esquemático y PCB |
| `esquematico.pdf` | Esquemático exportado, para verlo sin instalar nada |
| `gerbers/` | Archivos de fabricación (Gerber y taladros), los que se mandan al fabricante |
| `bom.csv` | Lista de componentes con su valor y su referencia |
| `fotos/` | Fotos de la placa montada (opcional) |

## De dónde salen las conexiones

Los pines y los componentes son los de [`firmware/README.md`](../firmware/README.md) (sección «Conexiones del Arduino UNO» y «UNO → ESP32») y de [`firmware/uno_sensores/config.h`](../firmware/uno_sensores/config.h). Si la PCB cambia algún pin, hay que cambiarlo también en `config.h` y avisar al electrónico.

Lo que no conviene olvidar:

- El RC522 va a **3,3 V**, nunca a 5 V.
- El TX del UNO llega al GPIO16 del ESP32 por un divisor 1 kΩ / 2 kΩ, con GND común.
- El termistor va en la **muñeca** del tripulante y la fotorresistencia y el LED del pulso, en el **dedo**: salen de la placa por cable.
