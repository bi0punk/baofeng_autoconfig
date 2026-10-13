#!/usr/bin/env python3
import argparse
import csv
import glob
import logging
import os
import sys
import time

import serial
from chirp import chirp_common, errors
from chirp.drivers import baofeng_common as bfc
from chirp.drivers.baofeng_wp970i import UV9R

from common import (
    cfg_setup_chirp,
    csv_row_to_power,
    open_serial_ok,
)

cfg_setup_chirp()
logging.basicConfig(level=logging.WARNING, format="%(message)s")
log = logging.getLogger("cli")

MAGIC = b"\x50\xbb\xff\x20\x14\x04\x13"
STIMEOUT = 1.5
DEFAULT_PORT = "/dev/ttyUSB0"
DRIVER_DIR = os.path.dirname(os.path.realpath(__file__))
DEFAULT_BACKUP = os.path.join(DRIVER_DIR, "img", "uv9r_backup.img")
DEFAULT_CSV = os.path.join(DRIVER_DIR, "canales.csv")


def find_port():
    candidates = sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))
    for p in candidates:
        s = open_serial_ok(p)
        if s is None:
            continue
        try:
            s.write(MAGIC)
            ack = s.read(1)
            s.close()
            if ack == b"\x06":
                return p
            if ack:
                time.sleep(0.5)
        except Exception:
            log.debug("Error probing %s", p, exc_info=True)
    for p in candidates:
        s = open_serial_ok(p)
        if s is not None:
            s.close()
            return p
    return None


def powercycle_ident(radio):
    pipe = radio.pipe
    pipe.baudrate = 9600
    pipe.parity = "N"
    pipe.timeout = 0.2

    bfc._clean_buffer(radio)

    radio.status_fn(chirp_common.Status(cur=0, max=1, msg="Envie magic; ENCIENDA EL RADIO AHORA"))

    start = time.time()
    while time.time() - start < 12:
        try:
            pipe.write(MAGIC)
            ack = pipe.read(1)
            if ack == b"\x06":
                pipe.write(b"\x02")
                pipe.timeout = STIMEOUT
                ident = pipe.read(8)
                pipe.timeout = 0.2
                if len(ident) == 8 and ident[0] == 0xAA and ident[-1] == 0xDD:
                    pipe.write(b"\x06")
                    if pipe.read(1) == b"\x06":
                        return ident
        except Exception:
            log.debug("Intento fallido en powercycle_ident", exc_info=True)
        time.sleep(0.05)

    raise errors.RadioError("No se recibio respuesta. Asegurese de encender el radio cuando se indique.")


def progress_status(status):
    if status.max == 0:
        return
    pct = int(status.cur / status.max * 100)
    bar_len = 20
    filled = int(bar_len * pct // 100)
    bar = "=" * filled + " " * (bar_len - filled)
    sys.stderr.write(f"\r  [{bar}] {pct:3d}%  {status.msg}")
    sys.stderr.flush()
    if pct >= 100:
        sys.stderr.write("\n")


def setup_radio(port):
    ser = serial.Serial(port=port, baudrate=9600, timeout=0.5)
    radio = UV9R(ser)
    radio.status_fn = progress_status
    bfc._ident_radio = powercycle_ident
    return radio, ser


def csv_rows(path):
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            rows.append(row)
    return rows


def apply_csv_to_radio(radio, rows, clear_before=True):
    rf = radio.get_features()
    start, end = rf.memory_bounds

    if clear_before:
        for i in range(start, end + 1):
            mem = chirp_common.Memory()
            mem.number = i
            mem.empty = True
            radio.set_memory(mem)

    for row in rows:
        loc = int(row.get("Location", 0))
        name = row.get("Name", "").strip()

        freq_mhz = float(row.get("Frequency", 0))
        if freq_mhz == 0:
            continue

        mem = chirp_common.Memory()
        mem.number = loc
        mem.freq = int(freq_mhz * 1_000_000)
        mem.name = name

        dup = row.get("Duplex", "").strip()
        mem.duplex = dup if dup else ""

        off_mhz = float(row.get("Offset", 0))
        mem.offset = int(off_mhz * 1_000_000)

        tone_mode = row.get("Tone", "").strip()
        cross = row.get("CrossMode", "").strip()
        rtf = row.get("rToneFreq", "88.5").strip()
        ctf = row.get("cToneFreq", "88.5").strip()
        dtcs_c = int(row.get("DtcsCode", 23))
        dtcs_pol = row.get("DtcsPolarity", "NN").strip()
        rx_dtcs = int(row.get("RxDtcsCode", 23))

        mem.cross_mode = cross if cross else "Tone->Tone"

        if tone_mode == "Tone":
            mem.tmode = "Tone"
            mem.rtone = float(rtf)
        elif tone_mode == "TSQL":
            mem.tmode = "TSQL"
            mem.ctone = float(ctf)
        elif tone_mode == "DTCS":
            mem.tmode = "DTCS"
            mem.dtcs = dtcs_c
            mem.dtcs_polarity = dtcs_pol
        elif tone_mode == "Cross" or (not tone_mode and cross):
            mem.tmode = "Cross"
            tx_mode, rx_mode = mem.cross_mode.split("->", 1)
            if tx_mode == "Tone":
                mem.rtone = float(rtf)
            elif tx_mode == "DTCS":
                mem.dtcs = dtcs_c
            if rx_mode == "Tone":
                mem.ctone = float(ctf)
            elif rx_mode == "DTCS":
                mem.rx_dtcs = rx_dtcs
        else:
            mem.tmode = ""

        if mem.tmode == "Cross":
            mem.dtcs_polarity = dtcs_pol

        mode_val = row.get("Mode", "FM").strip()
        mem.mode = mode_val if mode_val in ("FM", "NFM") else "FM"

        mem.skip = "S" if row.get("Skip", "").strip() == "S" else ""

        mem.power = csv_row_to_power(row.get("Power", "1"))

        radio.set_memory(mem)

    return len(rows)


def collect_radio_channels(radio):
    rf = radio.get_features()
    start, end = rf.memory_bounds
    channels = []
    for i in range(start, end + 1):
        mem = radio.get_memory(i)
        channels.append(mem)
    return channels


def format_channel(mem):
    if mem.empty:
        return "  VACIO"
    freq = mem.freq / 1e6
    name = mem.name.strip() if mem.name else ""
    name = name + " " * max(0, 9 - len(name))
    dup = mem.duplex if mem.duplex else "simplex"
    ct = f"t={mem.ctone}" if mem.ctone else ""
    rt = f"r={mem.rtone}" if mem.rtone and mem.rtone != mem.ctone else ""
    tone_info = f"{rt} {ct}".strip()
    power = str(mem.power) if mem.power else ""
    skip = "S" if mem.skip == "S" else ""
    return f"  {mem.number:3d}  {freq:8.4f}  {name}  {dup:7s}  {tone_info:12s}  {power:4s}  {skip}"


def cmd_download(args):
    radio, ser = setup_radio(args.port)
    try:
        radio.sync_in()
        out = args.img or DEFAULT_BACKUP
        radio.save_mmap(out)
        ch = collect_radio_channels(radio)
        non_empty = sum(1 for m in ch if not m.empty)
        print(f"Descargado: {out} ({len(radio.get_mmap())} bytes, {non_empty} canales)")
    finally:
        ser.close()


def cmd_upload(args):
    img = args.img or DEFAULT_BACKUP
    radio, ser = setup_radio(args.port)
    radio.load_mmap(img)
    try:
        radio.sync_out()
        print(f"\nSubida completada: {img}")
    finally:
        ser.close()


def cmd_list(args):
    if args.img:
        radio = UV9R(args.img)
        ch = collect_radio_channels(radio)
    else:
        radio, ser = setup_radio(args.port)
        try:
            radio.sync_in()
            ch = collect_radio_channels(radio)
        finally:
            ser.close()

    print(f"{'CH':3s}  {'Frecuencia':9s}  {'Nombre':9s}  {'Modo':7s}  {'Tono':12s}  {'Pot':4s}  {'Skip':4s}")
    print("-" * 60)
    non_empty = 0
    for mem in ch:
        if mem.empty:
            continue
        non_empty += 1
        print(format_channel(mem))
    print(f"\nTotal: {non_empty} canales")


def cmd_verify(args):
    csv_path = args.csv or DEFAULT_CSV
    rows = csv_rows(csv_path)
    expected = {}
    for row in rows:
        loc = int(row.get("Location", 0))
        expected[loc] = row

    radio, ser = setup_radio(args.port)
    try:
        radio.sync_in()
        errors_found = 0
        checked = 0
        for loc, row in expected.items():
            mem = radio.get_memory(loc)
            if mem.empty:
                print(f"  ERROR CH{loc}: canal vacio (esperado {row.get('Name')})")
                errors_found += 1
                continue
            checked += 1
            exp_freq = float(row.get("Frequency", 0))
            act_freq = mem.freq / 1e6
            if abs(act_freq - exp_freq) > 0.001:
                print(f"  ERROR CH{loc}: frecuencia {act_freq:.4f} != esperada {exp_freq:.4f}")
                errors_found += 1
            exp_name = row.get("Name", "").strip()
            act_name = mem.name.strip()
            if act_name != exp_name:
                print(f"  ERROR CH{loc}: nombre '{act_name}' != esperado '{exp_name}'")
                errors_found += 1
        if errors_found == 0:
            print(f"VERIFICACION OK: {checked} canales coinciden con el CSV")
        else:
            print(f"VERIFICACION: {errors_found} errores en {checked} canales")
    finally:
        ser.close()


def cmd_csv2img(args):
    csv_path = args.csv
    img_path = args.img
    out_path = args.output
    rows = csv_rows(csv_path)

    radio = UV9R(img_path if img_path else DEFAULT_BACKUP)

    count = apply_csv_to_radio(radio, rows)
    if out_path:
        radio.save_mmap(out_path)
        print(f"Imagen creada: {out_path} ({count} canales del CSV aplicados)")


def cmd_identify(args):
    radio, ser = setup_radio(args.port)
    try:
        powercycle_ident(radio)
        print("Radio identifcado correctamente")
    finally:
        ser.close()


def cmd_list_ports(args):
    ports = sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))
    if not ports:
        print("No se encontraron puertos serie USB")
        return
    for p in ports:
        try:
            s = serial.Serial(port=p, baudrate=9600, timeout=0.3)
            s.write(MAGIC)
            ack = s.read(1)
            s.close()
            marker = "  <-- RADIO DETECTADO" if ack == b"\x06" else ""
            print(f"  {p}{marker}")
        except Exception as e:
            print(f"  {p}  (error: {e})")


def main():
    if len(sys.argv) == 1:
        from tui import run_tui

        run_tui()
        return

    parser = argparse.ArgumentParser(
        description="Programador Baofeng UV-9R via CHIRP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Ejemplos:
  %(prog)s list-ports
  %(prog)s download --img uv9r_backup.img
  %(prog)s upload --img uv9r_backup.img
  %(prog)s list
  %(prog)s list --img uv9r_backup.img
  %(prog)s verify
  %(prog)s csv2img --csv freqs.csv --img uv9r_backup.img -o salida.img
""",
    )

    parser.add_argument("--port", default=None, help="Puerto serie (default: auto-detect)")

    sub = parser.add_subparsers(dest="command")

    p_down = sub.add_parser("download", help="Descargar canales del radio")
    p_down.add_argument("--img", default=None, help="Archivo .img de salida")

    p_up = sub.add_parser("upload", help="Subir canales al radio")
    p_up.add_argument("--img", default=None, help="Archivo .img de entrada")

    p_list = sub.add_parser("list", help="Listar canales")
    p_list.add_argument("--img", default=None, help="Listar desde archivo (no requiere radio)")

    p_ver = sub.add_parser("verify", help="Verificar canales vs CSV")
    p_ver.add_argument("--csv", default=None, help="Archivo CSV de referencia")

    p_c2i = sub.add_parser("csv2img", help="Convertir CSV a imagen CHIRP")
    p_c2i.add_argument("--csv", default=DEFAULT_CSV, help="Archivo CSV de entrada")
    p_c2i.add_argument("--img", default=None, help="Imagen base (default: backup existente)")
    p_c2i.add_argument("-o", "--output", default="uv9r_output.img", help="Archivo .img de salida")

    sub.add_parser("identify", help="Identificar radio (test de conexion)")
    sub.add_parser("list-ports", help="Listar puertos serie disponibles")

    args = parser.parse_args()

    if args.command == "list-ports":
        cmd_list_ports(args)
        return

    needs_port = ["download", "upload", "verify", "identify"]
    if args.command == "list" and not args.img:
        needs_port.append("list")
    if args.command in needs_port:
        port = args.port
        if not port:
            port = find_port()
            if not port:
                print("Error: no se encontro puerto serie. Use --port o conecte el cable.")
                sys.exit(1)
            print(f"Puerto detectado: {port}")
        args.port = port

    cmds = {
        "download": cmd_download,
        "upload": cmd_upload,
        "list": cmd_list,
        "verify": cmd_verify,
        "csv2img": cmd_csv2img,
        "identify": cmd_identify,
    }
    cmds[args.command](args)


if __name__ == "__main__":
    main()
