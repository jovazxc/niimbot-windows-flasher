# Firmware parcheado D110_M 4.33

Este es el parche del firmware oficial 4.30 que se instaló correctamente en
la impresora de desarrollo, no la reimplementación C.

- Modelo: **NIIMBOT D110_M**, identificador 2320.
- Versión de cabecera: **433 / 4.33**. Puede seguir anunciando 4.30 por Bluetooth.
- Permite iniciar impresión sin RFID y respeta intensidad 1–5.
- Sin chip, responde a la app con los datos del rollo original capturado durante
  el desarrollo; con chip, devuelve su lectura real.
- Ese respaldo es fijo: 186 etiquetas totales y 161 usadas. No es un perfil
  universal: la app puede seleccionar el tamaño del rollo original y aplicar
  límites del servidor.
- Conserva los indicadores físicos de papel/tapa y las rutinas térmicas.

Selecciona `D110_M_4.33_app-roll_EXPERIMENTAL.bin` en el actualizador.
Usa esta versión solo si la cabecera instalada es anterior a 4.33. Si ya
instalaste 4.33 o una posterior, no intentes reinstalarla o bajar de versión.
No se incrementa la versión del archivo automáticamente.

La impresora confirmó la instalación de este binario (0x9E=01) y se verificó
la respuesta de rollo por BLE. La aceptación final por la app oficial sigue
pendiente de confirmación. CRC válido no garantiza compatibilidad con otros
modelos. Hash SHA256 en `SHA256SUMS`.
