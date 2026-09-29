"""Windows 10/11 Tk UI; BLE lives in a dedicated, persistent MTA asyncio thread."""
import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from protocol import Firmware, SERVICE, operate

STORE = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'NiimbotFirmwareWindows'
STORE.mkdir(parents=True, exist_ok=True)

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('NIIMBOT D110_M · Actualizador de firmware'); self.geometry('810x690'); self.minsize(740, 640)
        self.events = queue.Queue(); self.busy = False; self.flashing = False
        self.devices = []; self.firmware = None; self.pending_address = None; self.pending_version = None
        try: self.history = json.loads((STORE / 'versions.json').read_text())
        except (OSError, ValueError): self.history = {}
        if not isinstance(self.history, dict): self.history = {}
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.worker, daemon=True).start()
        self.device = tk.StringVar(); self.version = tk.StringVar(); self.fw_label = tk.StringVar(value='Selecciona un firmware .bin completo.')
        self.status = tk.StringVar(value='Enciende la impresora y cierra NIIMBOT en el teléfono para liberar Bluetooth.')
        root = ttk.Frame(self, padding=24); root.pack(fill='both', expand=True)
        ttk.Label(root, text='Actualiza tu D110_M', font=('Segoe UI', 22, 'bold')).pack(anchor='w')
        ttk.Label(root, text='Windows · Bluetooth Low Energy', font=('Segoe UI', 11)).pack(anchor='w', pady=(4, 20))
        row = ttk.Frame(root); row.pack(fill='x')
        self.scan_button = ttk.Button(row, text='1. Buscar impresora', command=self.scan); self.scan_button.pack(side='left')
        self.combo = ttk.Combobox(row, textvariable=self.device, state='readonly'); self.combo.pack(side='left', fill='x', expand=True, padx=(12, 0))
        self.combo.bind('<<ComboboxSelected>>', self.selected)
        row = ttk.Frame(root); row.pack(fill='x', pady=(16, 8))
        self.file_button = ttk.Button(row, text='2. Elegir firmware .bin', command=self.choose); self.file_button.pack(side='left')
        ttk.Label(root, textvariable=self.fw_label, wraplength=730).pack(anchor='w', pady=(0, 14))
        row = ttk.Frame(root); row.pack(fill='x')
        ttk.Label(row, text='Última versión que instalaste (si la conoces):').pack(side='left')
        self.version_entry = ttk.Entry(row, textvariable=self.version, width=10); self.version_entry.pack(side='left', padx=10)
        ttk.Label(root, text='Ejemplo: 4.33. Los parches pueden seguir anunciando 4.30; esa respuesta no identifica la versión instalada.', wraplength=730).pack(anchor='w', pady=(6, 14))
        row = ttk.Frame(root); row.pack(fill='x')
        self.check_button = ttk.Button(row, text='Comprobar conexión', command=lambda:self.start(False)); self.check_button.pack(side='left')
        self.flash_button = ttk.Button(row, text='3. Instalar firmware', command=lambda:self.start(True)); self.flash_button.pack(side='left', padx=12)
        self.progress = ttk.Progressbar(root, maximum=100); self.progress.pack(fill='x', pady=(18, 10))
        ttk.Label(root, textvariable=self.status, wraplength=730).pack(anchor='w')
        self.log = ScrolledText(root, height=12, state='disabled', font=('Consolas', 9)); self.log.pack(fill='both', expand=True, pady=(12, 8))
        ttk.Label(root, text='No apagues la impresora durante la transferencia. Un CRC válido no demuestra que una reimplementación pueda arrancar.', wraplength=730).pack(anchor='w')
        ttk.Label(root, text=f'Registros: {STORE}', wraplength=730).pack(anchor='w', pady=(6, 0))
        self.protocol('WM_DELETE_WINDOW', self.close); self.after(100, self.poll)

    def worker(self):
        sys.coinit_flags = 0
        asyncio.set_event_loop(self.loop); self.loop.run_forever()
    def emit(self, kind, value): self.events.put((kind, value))
    def launch(self, coroutine):
        async def wrapped():
            try: await coroutine
            except Exception as error: self.emit('error', str(error) or type(error).__name__)
            finally: self.emit('done', None)
        self.busy = True; self.controls(False)
        asyncio.run_coroutine_threadsafe(wrapped(), self.loop)
    def controls(self, enabled):
        for widget in (self.scan_button, self.file_button, self.check_button, self.flash_button, self.version_entry):
            widget.configure(state='normal' if enabled else 'disabled')
        self.combo.configure(state='readonly' if enabled else 'disabled')
    def write_log(self, value):
        self.log.configure(state='normal'); self.log.insert('end', value+'\n'); self.log.see('end'); self.log.configure(state='disabled')
    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'devices':
                    self.devices = value
                    self.combo['values'] = [f'{name} — {addr} ({rssi} dBm)' for name, addr, rssi in value]
                    if value: self.combo.current(0); self.selected()
                    else: self.status.set('No se detectó una NIIMBOT. Revisa Bluetooth y desconecta la app del teléfono.')
                elif kind == 'progress': self.progress['value'] = value
                elif kind in ('phase', 'disconnected'): self.status.set(value); self.write_log(value)
                elif kind == 'error':
                    self.status.set('Operación detenida.'); self.write_log('ERROR: '+value)
                    if self.flashing: value += '\nNo se reintentó automáticamente. Revisa el registro antes de volver a actualizar.'
                    messagebox.showerror('Operación detenida', value)
                elif kind == 'success':
                    address, version = value
                    self.history[address] = version
                    try: (STORE/'versions.json').write_text(json.dumps(self.history, indent=2), encoding='utf-8')
                    except OSError as error: self.write_log(f'No se pudo guardar el historial: {error}')
                    self.version.set(f'{version // 100}.{version % 100:02d}')
                    messagebox.showinfo('Actualización confirmada', 'La impresora confirmó la actualización.\nSi se apagó, enciéndela manualmente.')
                elif kind == 'done': self.busy = False; self.flashing = False; self.controls(True)
        except queue.Empty: pass
        self.after(100, self.poll)
    def selected(self, *_):
        idx = self.combo.current()
        if idx < 0: return
        known = self.history.get(self.devices[idx][1])
        self.version.set(f'{known // 100}.{known % 100:02d}' if isinstance(known, int) else '')
    def choose(self):
        path = filedialog.askopenfilename(filetypes=[('Firmware NIIMBOT', '*.bin')])
        if not path: return
        self.firmware = None
        try:
            if Path(path).stat().st_size > 0x20000+28: raise ValueError('Archivo demasiado grande para este actualizador D110_M.')
            self.firmware = Firmware.parse(Path(path).read_bytes())
            fw = self.firmware
            self.fw_label.set(f'{Path(path).name}\nVersión {fw.display_version} · D110_M · {len(fw.data):,} bytes · CRC correctos\nSHA256: {fw.sha256}')
        except Exception as error:
            self.fw_label.set('Archivo rechazado.'); messagebox.showerror('Firmware no válido', str(error))
    def scan(self):
        self.status.set('Buscando por Bluetooth durante 8 segundos…')
        async def discover():
            from bleak import BleakScanner
            devices = await BleakScanner.discover(timeout=8, return_adv=True)
            found = []
            for device, adv in devices.values():
                name = adv.local_name or device.name or 'Sin nombre'
                if 'd110' in name.lower() or 'niimbot' in name.lower() or SERVICE in [s.lower() for s in adv.service_uuids]:
                    found.append((name, device.address, adv.rssi))
            found.sort(key=lambda x:x[2], reverse=True)
            self.emit('devices', found); self.emit('phase', f'Búsqueda terminada: {len(found)} dispositivos compatibles anunciados.')
        self.launch(discover())
    def start(self, flash):
        idx = self.combo.current()
        if idx < 0: messagebox.showinfo('Impresora', 'Busca y selecciona la impresora primero.'); return
        if flash and self.firmware is None: messagebox.showinfo('Firmware', 'Elige un .bin válido primero.'); return
        known = None
        if self.version.get().strip():
            try:
                major, minor = self.version.get().strip().split('.')
                if not (major.isdigit() and minor.isdigit() and 0 <= int(major) <= 255 and 0 <= int(minor) < 100): raise ValueError()
                known = int(major)*100+int(minor)
            except ValueError: messagebox.showerror('Versión', 'Usa el formato 4.33.'); return
        if flash and known is not None and self.firmware.version <= known:
            messagebox.showerror('Versión', 'El firmware debe tener una versión mayor que la última instalada.'); return
        address = self.devices[idx][1]; fw = self.firmware
        logfile = STORE / f'{datetime.now():%Y%m%d-%H%M%S-%f}.jsonl'
        self.flashing = flash; self.progress['value'] = 0
        self.write_log(f"{'Actualización' if flash else 'Comprobación'} · {address}\nRegistro: {logfile}")
        async def work():
            await operate(address, fw, known, flash, logfile, self.emit)
            if flash: self.emit('success', (address, fw.version))
        self.launch(work())
    def close(self):
        if self.busy:
            messagebox.showinfo('Operación en curso', 'Espera a que termine la operación Bluetooth antes de cerrar.'); return
        self.loop.call_soon_threadsafe(self.loop.stop); self.destroy()

if __name__ == '__main__': App().mainloop()
