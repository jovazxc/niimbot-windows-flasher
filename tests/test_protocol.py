import struct
import unittest
import zlib
from protocol import Decoder, Firmware, packet, preflight, upload

def make_image(size=450, version=434, model=2320):
    payload = bytes(i % 251 for i in range(size))
    header = bytearray(28); header[:4] = b'\x18\x12\x34\x56'
    struct.pack_into('<II', header, 4, size, zlib.crc32(payload))
    struct.pack_into('<HH', header, 20, version, model)
    normalized = bytearray(header[:24]); normalized[1:4] = b'\0'*3
    struct.pack_into('<I', header, 24, zlib.crc32(normalized))
    return bytes(header) + payload

class FormatTests(unittest.TestCase):
    def test_valid_image(self):
        fw = Firmware.parse(make_image()); self.assertEqual(fw.version, 434); self.assertEqual(fw.display_version, '4.34')
    def test_wrong_model(self):
        with self.assertRaisesRegex(ValueError, 'modelo'): Firmware.parse(make_image(model=1))
    def test_payload_corruption(self):
        b = bytearray(make_image()); b[-1] ^= 1
        with self.assertRaisesRegex(ValueError, 'payload'): Firmware.parse(b)
    def test_header_corruption(self):
        b = bytearray(make_image()); b[20] ^= 1
        with self.assertRaisesRegex(ValueError, 'cabecera'): Firmware.parse(b)
    def test_truncation_and_raw_payload(self):
        for b in (b'', make_image()[:-1], make_image()[28:]):
            with self.assertRaises(ValueError): Firmware.parse(b)
    def test_known_simple_packet(self): self.assertEqual(packet(0xc1, b'\1').hex(), '5555c10101c1aaaa')
    def test_fragmented_and_coalesced_frames(self):
        frames = [(0xc2, 0, b'\3'), (0x9b, 37, bytes(range(200))), (0x9d, 0, b'\1')]
        stream = b''.join(packet(c,d,i) for c,i,d in frames)
        for step in (1, 2, 3, 20, 128, len(stream)):
            decoder = Decoder(); got = []
            for offset in range(0, len(stream), step): got.extend(decoder.feed(stream[offset:offset+step]))
            self.assertEqual(got, frames); self.assertFalse(decoder.buffer)
    def test_invalid_frame_crc(self):
        b = bytearray(packet(0x9a, b'', 1)); b[-3] ^= 1
        with self.assertRaises(ValueError): Decoder().feed(b)

class FakeChannel:
    def __init__(self, incoming=(), info=None):
        self.incoming = list(incoming); self.sent = []; self.info = info or {}
    async def send(self, cmd, data=b'', chunk=0): self.sent.append((cmd, chunk, data))
    async def request(self, cmd, data, expected):
        await self.send(cmd, data)
        if cmd == 0xf5: return self.info.get('upgrade', b'\1')
        if cmd == 0xc1: return self.info.get('protocol', b'\3')
        defaults = {8:b'\x09\x10',9:b'\x04\x1e',10:b'\3',12:b'\4\1'}
        return self.info.get(data[0], defaults[data[0]])
    async def receive(self, commands, timeout=20):
        if not self.incoming: raise TimeoutError('simulation timeout')
        result = self.incoming.pop(0)
        assert result[0] in commands, (result,commands)
        return result
    def event(self, *args, **kwargs): pass

def replies(check=b'\1', final=b'\1'):
    return [(0x90,0,b''), (0x9a,0,b''), (0x9a,1,b''), (0x9a,1,b''), (0x9a,2,b''), (0x9a,3,b''), (0x9d,0,check), (0x9e,0,final)]

class TransferTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_image_and_requested_repeat(self):
        fw = Firmware.parse(make_image()); ch = FakeChannel(replies()); events = []
        await upload(ch, fw, lambda *args: events.append(args))
        self.assertEqual(ch.sent[0], (0xf5,0,b'\4\x22'))
        self.assertEqual(ch.sent[1], (0x91,0,struct.pack('>I',zlib.crc32(fw.data))))
        chunks = {i:d for c,i,d in ch.sent if c==0x9b}
        self.assertEqual(b''.join(chunks[i] for i in sorted(chunks)),fw.data)
        self.assertEqual(sum(1 for c,i,d in ch.sent if c==0x9b and i==1),2)
        self.assertEqual(ch.sent[-2:],[(0x9c,0,b'\1'),(0x92,0,b'\1')])
    async def test_missing_chunks_never_commit(self):
        ch = FakeChannel([(0x90,0,b''),(0x9a,0,b''),(0x9a,3,b'')])
        with self.assertRaisesRegex(RuntimeError,'incompleta'): await upload(ch,Firmware.parse(make_image()),lambda *a:None)
        self.assertNotIn(0x92,[c for c,_,_ in ch.sent])
    async def test_validation_failure_never_commits(self):
        ch = FakeChannel(replies(check=b'\0'))
        with self.assertRaisesRegex(RuntimeError,'rechazó'): await upload(ch,Firmware.parse(make_image()),lambda *a:None)
        self.assertNotIn(0x92,[c for c,_,_ in ch.sent])
    async def test_final_rejection(self):
        ch = FakeChannel(replies(final=b'\0'))
        with self.assertRaisesRegex(RuntimeError,'no confirmó'): await upload(ch,Firmware.parse(make_image()),lambda *a:None)
    async def test_upgrade_rejection(self):
        ch = FakeChannel(info={'upgrade':b'\0'})
        with self.assertRaises(RuntimeError): await upload(ch,Firmware.parse(make_image()),lambda *a:None)
        self.assertEqual(len(ch.sent),1)
    async def test_final_timeout(self):
        ch = FakeChannel(replies()[:-1])
        with self.assertRaises(TimeoutError): await upload(ch,Firmware.parse(make_image()),lambda *a:None)
    async def test_preflight_success(self): self.assertEqual((await preflight(FakeChannel()))['model'],b'\x09\x10')
    async def test_wrong_model_battery_protocol(self):
        for info in ({8:b'\0\1'}, {10:b'\2'}, {'protocol':b'\2'}):
            with self.assertRaises(RuntimeError): await preflight(FakeChannel(info=info))

if __name__ == '__main__': unittest.main()
