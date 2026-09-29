"""D110_M firmware format and BLE updater; GUI independent, mock-testable."""
import asyncio
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import struct
import time
import zlib

CHAR = 'bef8d6c9-9c21-4c9e-b632-bd58c1009f9f'
SERVICE = 'e7810a71-73ae-499d-8c15-faa9aef0c3f2'
CRC_COMMANDS = {0x90, 0x91, 0x92, 0x9a, 0x9b, 0x9c, 0x9d, 0x9e}

@dataclass(frozen=True)
class Firmware:
    data: bytes
    version: int
    sha256: str
    @property
    def display_version(self): return f'{self.version // 100}.{self.version % 100:02d}'
    @classmethod
    def parse(cls, data):
        data = bytes(data)
        if len(data) < 28 or data[0] != 0x18:
            raise ValueError('No es un firmware NIIMBOT completo: falta la cabecera de 28 bytes.')
        length, checksum = struct.unpack_from('<II', data, 4)
        if length != len(data) - 28 or not 0 < length <= 0x20000:
            raise ValueError('Longitud del payload incorrecta o fuera del límite admitido de 128 KiB.')
        if zlib.crc32(data[28:]) != checksum: raise ValueError('CRC del payload incorrecto.')
        header = bytearray(data[:24]); header[1:4] = b'\0\0\0'
        if zlib.crc32(header) != struct.unpack_from('<I', data, 24)[0]: raise ValueError('CRC de cabecera incorrecto.')
        version, model = struct.unpack_from('<HH', data, 20)
        if model != 2320: raise ValueError(f'El archivo es para el modelo {model}; solo se admite D110_M (2320).')
        if not 0 < version <= 25599: raise ValueError('Versión incompatible con el protocolo de actualización.')
        return cls(data, version, hashlib.sha256(data).hexdigest())


def packet(cmd, data=b'', chunk=0):
    if len(data) > 255: raise ValueError('Paquete demasiado grande')
    if cmd in CRC_COMMANDS:
        body = bytes([cmd]) + struct.pack('>H', chunk) + bytes([len(data)]) + data
        check = struct.pack('>I', zlib.crc32(body))
    else:
        body = bytes([cmd, len(data)]) + data
        xor = 0
        for value in body: xor ^= value
        check = bytes([xor])
    return b'\x55\x55' + body + check + b'\xaa\xaa'

class Decoder:
    def __init__(self): self.buffer = bytearray()
    def feed(self, incoming):
        self.buffer.extend(incoming); result = []
        while len(self.buffer) >= 4:
            if self.buffer[:2] != b'\x55\x55': raise ValueError('Cabecera BLE inesperada.')
            cmd = self.buffer[2]; crc = cmd in CRC_COMMANDS; pos = 5 if crc else 3
            if len(self.buffer) <= pos: break
            length = self.buffer[pos]; total = pos + 1 + length + (4 if crc else 1) + 2
            if len(self.buffer) < total: break
            raw = bytes(self.buffer[:total]); del self.buffer[:total]
            data = raw[pos + 1:pos + 1 + length]
            chunk = int.from_bytes(raw[3:5], 'big') if crc else 0
            if raw != packet(cmd, data, chunk): raise ValueError('CRC o cierre del paquete BLE incorrecto.')
            result.append((cmd, chunk, data))
        return result

class Channel:
    def __init__(self, client, log):
        self.client = client; self.log = log; self.decoder = Decoder(); self.queue = asyncio.Queue()
        self.loop = asyncio.get_running_loop()
    def event(self, kind, **kw):
        if self.log.closed: return
        self.log.write(json.dumps(dict(t=time.time(), kind=kind, **kw)) + '\n'); self.log.flush()
    def notify(self, _, value): self.loop.call_soon_threadsafe(self._incoming, bytes(value))
    def _incoming(self, value):
        self.event('rx', hex=value.hex())
        try:
            for decoded in self.decoder.feed(value): self.queue.put_nowait(decoded)
        except Exception as error: self.queue.put_nowait(error)
    def disconnected(self, _):
        self.loop.call_soon_threadsafe(self.queue.put_nowait, ConnectionError('Bluetooth desconectado.'))
    async def send(self, cmd, data=b'', chunk=0):
        raw = packet(cmd, data, chunk); self.event('tx', hex=raw.hex())
        char = self.client.services.get_characteristic(CHAR)
        if char is None: raise RuntimeError('No se encontró el servicio Bluetooth de NIIMBOT.')
        limit = min(char.max_write_without_response_size, 512)
        if limit < 20: raise RuntimeError('Tamaño de escritura BLE inválido.')
        for offset in range(0, len(raw), limit):
            await self.client.write_gatt_char(char, raw[offset:offset + limit], response=False)
            if len(raw) > limit: await asyncio.sleep(.01)
    async def receive(self, commands, timeout=20):
        end = self.loop.time() + timeout
        while True:
            try: result = await asyncio.wait_for(self.queue.get(), max(0, end - self.loop.time()))
            except asyncio.TimeoutError as error: raise TimeoutError('La impresora no respondió a tiempo.') from error
            if isinstance(result, Exception): raise result
            if result[0] in commands: return result
            self.event('unrelated', cmd=result[0], data=result[2].hex())
    async def request(self, cmd, data, expected):
        await self.send(cmd, data)
        return (await self.receive({expected}))[2]

async def preflight(ch):
    protocol = await ch.request(0xc1, b'\1', 0xc2)
    if protocol != b'\3': raise RuntimeError(f'Protocolo no admitido: {protocol.hex()} (se requiere v3).')
    info = {}
    for key, name in ((8, 'model'), (9, 'software'), (10, 'battery'), (12, 'hardware')):
        info[name] = await ch.request(0x40, bytes([key]), 0x40 + key)
    if info['model'] != b'\x09\x10': raise RuntimeError('La impresora conectada no es una D110_M.')
    if len(info['battery']) != 1 or not 3 <= info['battery'][0] <= 4:
        raise RuntimeError('Carga la batería hasta al menos el nivel 3/4 antes de actualizar.')
    ch.event('preflight', **{k: v.hex() for k, v in info.items()})
    return info

async def upload(ch, fw, emit):
    emit('phase', 'Preparando actualización; no apagues la impresora.')
    response = await ch.request(0xf5, bytes([fw.version // 100, fw.version % 100]), 0xf6)
    if response != b'\1': raise RuntimeError(f'Actualización rechazada ({response.hex()}). Comprueba la versión instalada.')
    await ch.receive({0x90})
    await ch.send(0x91, struct.pack('>I', zlib.crc32(fw.data)))
    count = (len(fw.data) + 199) // 200; seen = set(); requests = 0
    while True:
        cmd, idx, data = await ch.receive({0x9a, 0x9e})
        if cmd == 0x9e: raise RuntimeError(f'Resultado prematuro de actualización: {data.hex()}')
        requests += 1
        if requests > count * 4: raise RuntimeError('Demasiados reintentos de bloques.')
        if idx >= count:
            if idx != count or len(seen) != count: raise RuntimeError('Transferencia incompleta: faltan bloques.')
            break
        await ch.send(0x9b, fw.data[idx * 200:(idx + 1) * 200], idx)
        seen.add(idx); emit('progress', len(seen) * 100 / count)
    await ch.send(0x9c, b'\1')
    _, _, check = await ch.receive({0x9d}, timeout=30)
    if check != b'\1': raise RuntimeError(f'La impresora rechazó el archivo: {check.hex()}')
    emit('phase', 'Archivo validado por la impresora. Aplicando firmware…')
    await ch.send(0x92, b'\1')
    _, _, result = await ch.receive({0x9e}, timeout=30)
    if result != b'\1': raise RuntimeError(f'La impresora no confirmó la actualización: {result.hex()}')
    ch.event('update_success', sha256=fw.sha256, version=fw.version)
    emit('phase', 'Actualización confirmada (0x9E=01). Si se apagó, enciéndela manualmente.')

async def operate(address, fw, known_version, do_flash, log_path, emit):
    from bleak import BleakClient
    if do_flash and known_version is not None and fw.version <= known_version:
        raise RuntimeError('La versión del archivo debe ser mayor que la última versión que instalaste.')
    channel = None
    with Path(log_path).open('x', encoding='utf-8') as log:
        def disconnected(client):
            if channel is not None: channel.disconnected(client)
        async with BleakClient(address, timeout=25, disconnected_callback=disconnected) as client:
            channel = Channel(client, log)
            await client.start_notify(CHAR, channel.notify)
            info = await preflight(channel)
            software = '.'.join(str(v) for v in info['software'])
            emit('phase', f"D110_M verificada · versión anunciada {software} · batería {info['battery'][0]}/4")
            if do_flash:
                if len(info['software']) != 2: raise RuntimeError('Versión anunciada no reconocida.')
                announced = info['software'][0] * 100 + info['software'][1]
                if fw.version <= announced: raise RuntimeError('La versión del archivo no supera la anunciada por la impresora.')
                await upload(channel, fw, emit)
        emit('disconnected', 'Bluetooth desconectado.')
