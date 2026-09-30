# NIIMBOT D110_M — Actualizador para Windows

Interfaz gráfica en Python para subir un firmware completo `.bin` a una D110_M
por Bluetooth Low Energy. Comprueba modelo, batería, longitud y ambos CRC;
transfiere bloques y espera la confirmación final de la impresora.

## Descargar y abrir

Descarga el ZIP de [Releases](https://github.com/jovazxc/niimbot-windows-flasher/releases),
extrae todo su contenido y abre **Abrir.cmd**.

Requiere **Windows 10/11, Bluetooth LE y Python 3.10 o posterior con Tcl/Tk**.
La primera ejecución instala Bleak automáticamente en una carpeta `.venv`.
Es una aplicación Python con lanzador, no un EXE independiente.

1. Enciende la impresora y desconecta NIIMBOT del teléfono.
2. Pulsa **Buscar impresora** y selecciona la D110_M.
3. Elige el firmware `.bin` completo, con cabecera de 28 bytes.
4. Indica la última versión instalada si la conoces.
5. Pulsa **Instalar firmware** y espera la confirmación.
6. Si la impresora se apaga al terminar, enciéndela manualmente.

**Comprobar conexión** no flashea ni imprime. Bluetooth se desconecta al terminar.
Los registros quedan en `%LOCALAPPDATA%\NiimbotFirmwareWindows`.

## Firmware incluido

El binario parcheado está en [`firmware/D110_M_4.33_app-roll_EXPERIMENTAL.bin`](firmware/D110_M_4.33_app-roll_EXPERIMENTAL.bin).
Lee sus [notas y limitaciones](firmware/README.md) antes de seleccionarlo.
La carpeta está incluida al descargar el código actual; el ZIP inicial de la release v1.0.0 contiene solo el programa.

## Compatibilidad y límites

- Solo modelo **2320 / D110_M**, protocolo v3, payload de hasta 128 KiB.
- Incluye el [firmware parcheado 4.33](firmware/README.md). No convierte ELF/payloads en imágenes flasheables.
- La versión debe superar la instalada. Un parche puede anunciar 4.30 por BLE
  aunque su cabecera instalada sea 4.33; el programa no puede detectar esa
  cabecera con la consulta normal. No modifica versiones ni CRC automáticamente.
- Un CRC válido no garantiza que un firmware nuevo pueda arrancar.
- No hay reintentos automáticos de la actualización completa.
- No apagues la impresora ni cierres el programa durante la transferencia.

## Verificación

16 pruebas locales de formato, corrupción, fragmentación y transferencia simulada.
Protocolo basado en el actualizador BLE utilizado con esta impresora en macOS.
La interfaz y el transporte WinRT todavía no se han probado en Windows real.

```sh
python -m unittest discover -s tests -v
```

Consulta [LEEME.txt](LEEME.txt) para instrucciones completas.

## Imprimir una etiqueta de prueba

Abre **Imprimir-prueba.cmd**, elige la impresora detectada y espera una etiqueta
**40 × 12 mm** con el texto «Prueba OK». Intensidad 3 por defecto. Cierra antes
la app NIIMBOT del teléfono. El lanzador instala Pillow la primera vez.
No flashea; desconecta Bluetooth al terminar.

Para cambiar intensidad: `Imprimir-prueba.cmd --density 5`.
También puedes usar `python print_test.py --address AA:BB:CC:DD:EE:FF --density 3`.
La vista previa y el registro se guardan en
`%LOCALAPPDATA%\NiimbotFirmwareWindows\experimental`.
