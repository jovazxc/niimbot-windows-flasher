"""Print one 40x12 mm label using the B1 task protocol, with checked replies."""
import argparse, asyncio, json, os, struct, time
from pathlib import Path
from bleak import BleakClient, BleakScanner
from protocol import Channel, CHAR, SERVICE
ROOT=Path(os.environ.get('LOCALAPPDATA', str(Path.home())))/'NiimbotFirmwareWindows'
(ROOT/'experimental').mkdir(parents=True,exist_ok=True)
from PIL import Image, ImageDraw, ImageFont

async def print_label(address, density=3):
    if density not in range(1,6):raise ValueError("Density must be 1..5")
    img=Image.new('1',(320,96),1);d=ImageDraw.Draw(img)
    d.rectangle((5,5,314,90),outline=0,width=2)
    font_path=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'arialbd.ttf'
    try: font=ImageFont.truetype(str(font_path),40)
    except OSError: font=ImageFont.load_default(size=36)
    text='Prueba OK';box=d.textbbox((0,0),text,font=font)
    d.text(((320-(box[2]-box[0]))//2-box[0],(96-(box[3]-box[1]))//2-box[1]),text,font=font,fill=0)
    img.save(ROOT/'experimental'/'label-test.png')
    raster=img.rotate(-90,expand=True);lines=[]
    for y in range(320):
        row=bytearray(12)
        for x in range(96):
            if raster.getpixel((x,y))==0:row[x//8]|=1<<(7-x%8)
        lines.append(bytes(row))
    logfile=ROOT/'experimental'/f'print-{time.strftime("%Y%m%d-%H%M%S")}.jsonl'
    with logfile.open('x') as log:
        async with BleakClient(address,timeout=20) as cl:
            ch=Channel(cl,log);await cl.start_notify(CHAR,ch.notify)
            async def request(cmd,data,rx):
                await ch.send(cmd,data)
                got,_,answer=await ch.receive({rx,0xdb},timeout=10)
                print(f'{cmd:02x} -> {got:02x} {answer.hex()}',flush=True)
                if got==0xdb:raise RuntimeError(f'Printer error {int.from_bytes(answer,"big")}')
                return answer
            if await request(0xc1,b'\1',0xc2)!=b'\3':raise RuntimeError('Se requiere protocolo v3')
            if await request(0x40,b'\x08',0x48)!=bytes.fromhex('0910'):raise RuntimeError('Wrong printer')
            rfid=await request(0x1a,b'\1',0x1b)
            started=False;status=None
            try:
                for cmd,data,rx in ((0x21,bytes([density]),0x31),(0x23,b'\1',0x33),(0x01,bytes.fromhex('00010000000000'),0x02),(0x03,b'\1',0x04),(0x13,bytes.fromhex('014000600001'),0x14)):
                    answer=await request(cmd,data,rx)
                    if not answer or answer[0]!=1:raise RuntimeError(f'Command {cmd:02x} rejected')
                    if cmd==1:started=True
                    if cmd==0x21:
                        actual=await request(0x40,b"\x01",0x41)
                        if actual!=bytes([density]):raise RuntimeError("Density readback mismatch")
                y=0
                while y<320:
                    row=lines[y];n=1
                    while y+n<320 and lines[y+n]==row and n<255:n+=1
                    prefix=struct.pack('>H',y)
                    if not any(row):await ch.send(0x84,prefix+bytes([n]))
                    else:
                        counts=[sum(b.bit_count() for b in row[i*4:i*4+4]) for i in range(3)]
                        await ch.send(0x85,prefix+bytes(counts)+bytes([n])+row)
                    y+=n;await asyncio.sleep(.01)
                    while not ch.queue.empty():
                        p=ch.queue.get_nowait()
                        if isinstance(p,Exception):raise p
                        if p[0]==0xdb:raise RuntimeError(f'Printer error while sending: {p[2].hex()}')
                if await request(0xe3,b'\1',0xe4)!=b'\1':raise RuntimeError('PageEnd rejected')
                for _ in range(60):
                    raw=await request(0xa3,b'\1',0xb3)
                    if len(raw)<4:raise RuntimeError('Short print status')
                    status={'page':int.from_bytes(raw[:2],'big'),'print_progress':raw[2],'feed_progress':raw[3],'error':raw[6] if len(raw)==10 else 0}
                    if status['error']:raise RuntimeError(f'Print status error: {status}')
                    if status['page']>=1:break
                    await asyncio.sleep(.3)
                else:raise RuntimeError(f'Print completion timeout: {status}')
                result={'density':density,'rfid':rfid.hex(),'status':status,'visual_quality':'pending user observation','log':logfile.name}
                (ROOT/'experimental'/'print-test-result.json').write_text(json.dumps(result,indent=2)+'\n')
                print('PRINTER REPORTS PAGE COMPLETE',json.dumps(result),flush=True)
            finally:
                if started:
                    try:await request(0xf3,b'\1',0xf4)
                    except Exception as e:print('PrintEnd:',e,flush=True)

async def main(args):
    address=args.address
    if not address:
        print('Buscando impresora durante 8 segundos...',flush=True)
        found=await BleakScanner.discover(timeout=8,return_adv=True)
        devices=[(d,a) for d,a in found.values() if 'd110' in (a.local_name or d.name or '').lower() or 'niimbot' in (a.local_name or d.name or '').lower() or SERVICE in a.service_uuids]
        if not devices:raise RuntimeError('No se encontro la impresora. Enciendela y desconectala de la app del telefono.')
        for i,(d,a) in enumerate(devices,1):print(f'{i}. {a.local_name or d.name} - {d.address}')
        choice=int(input('Numero de impresora: '))
        if not 1<=choice<=len(devices):raise ValueError('Seleccion invalida')
        address=devices[choice-1][0].address
    print(f'Imprimiendo UNA etiqueta 40x12 mm, intensidad {args.density}.',flush=True)
    await print_label(address,args.density)
    print('Bluetooth desconectado. Revisa la etiqueta.',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Imprime una etiqueta de prueba 40x12 mm en D110_M; no flashea.')
    parser.add_argument('--address',help='Direccion Bluetooth de Windows, opcional')
    parser.add_argument('--density',type=int,choices=range(1,6),default=3)
    args=parser.parse_args()
    try:asyncio.run(main(args))
    except (Exception,KeyboardInterrupt) as error:
        print(f'ERROR: {error}',flush=True)
        raise SystemExit(1)

