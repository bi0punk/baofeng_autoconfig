#!/usr/bin/env python3
import os
os.environ.setdefault("CHIRP_TESTENV", "1")

import sys
sys.path.insert(0, "/usr/lib/python3/dist-packages")

import csv
import math
import tempfile
from typing import Optional

from textual.app import App, ComposeResult
from textual.screen import Screen, ModalScreen
from textual.containers import Horizontal, Vertical, Container, Center
from textual.widgets import (
    Header, Footer, DataTable, Input, Select, Button,
    Label, Static, ProgressBar
)
from textual.binding import Binding
from textual import work
from textual.coordinate import Coordinate

from chirp import chirp_common, errors
from chirp.drivers.baofeng_wp970i import UV9R

from cli import (
    MAGIC, STIMEOUT, POWER_LEVELS, DEFAULT_PORT, DEFAULT_BACKUP, DEFAULT_CSV,
    DRIVER_DIR, find_port, powercycle_ident, setup_radio, csv_rows,
    apply_csv_to_radio, collect_radio_channels, format_channel
)

TUI_CSS = """
Screen {
    background: $surface;
}

MainScreen > Vertical {
    height: 1fr;
}

DataTable {
    height: 1fr;
    margin: 0 1;
}

.status-bar {
    height: 1;
    background: $panel;
    padding: 0 1;
    dock: bottom;
}

.status-bar > Label {
    width: 1fr;
}

/* ----- modals ----- */
EditChannel {
    align: center middle;
}
EditChannel > Vertical {
    width: 52;
    height: auto;
    max-height: 100%;
    border: thick $primary;
    padding: 1 2;
    background: $surface;
}
EditChannel Label.field-label {
    margin-top: 1;
    text-style: bold;
}
EditChannel Input, EditChannel Select {
    width: 100%;
}
EditChannel .button-row {
    height: auto;
    margin-top: 1;
    align: center middle;
}

ConfirmScreen { align: center middle; }
ConfirmScreen > Vertical {
    width: 40;
    height: auto;
    border: thick $primary;
    padding: 1 2;
    background: $surface;
}
ConfirmScreen .button-row { align: center middle; margin-top: 1; }

AlertScreen { align: center middle; }
AlertScreen > Vertical {
    width: 40;
    height: auto;
    border: thick $primary;
    padding: 1 2;
    background: $surface;
}
AlertScreen .button-row { align: center middle; margin-top: 1; }

InputScreen { align: center middle; }
InputScreen > Vertical {
    width: 50;
    height: auto;
    border: thick $primary;
    padding: 1 2;
    background: $surface;
}
InputScreen .button-row { align: center middle; margin-top: 1; }

ProgressScreen { align: center middle; }
ProgressScreen > Vertical {
    width: 40;
    height: auto;
    border: thick $primary;
    padding: 1;
    background: $surface;
}
"""


class ConfirmScreen(ModalScreen[bool]):
    def __init__(self, title: str, message: str):
        super().__init__()
        self._title = title
        self._message = message

    def compose(self):
        with Vertical():
            yield Label(self._title, id="confirm-title")
            yield Label(self._message, id="confirm-msg")
            with Horizontal(classes="button-row"):
                yield Button("Si", id="yes", variant="primary")
                yield Button("No", id="no", variant="default")

    def on_button_pressed(self, event: Button.Pressed):
        self.dismiss(event.button.id == "yes")


class AlertScreen(ModalScreen[None]):
    def __init__(self, title: str, message: str):
        super().__init__()
        self._title = title
        self._message = message

    def compose(self):
        with Vertical():
            yield Label(self._title, id="alert-title")
            yield Label(self._message, id="alert-msg")
            with Horizontal(classes="button-row"):
                yield Button("OK", id="ok", variant="primary")

    def on_button_pressed(self, event: Button.Pressed):
        self.dismiss(None)


class InputScreen(ModalScreen[Optional[str]]):
    def __init__(self, title: str, label: str, value: str = ""):
        super().__init__()
        self._title = title
        self._label = label
        self._value = value

    def compose(self):
        with Vertical():
            yield Label(self._title, id="input-title")
            yield Label(self._label)
            yield Input(value=self._value, id="input-field")
            with Horizontal(classes="button-row"):
                yield Button("Aceptar", id="ok", variant="primary")
                yield Button("Cancelar", id="cancel")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "ok":
            val = self.query_one("#input-field", Input).value.strip()
            self.dismiss(val if val else None)
        else:
            self.dismiss(None)


class EditChannel(ModalScreen[Optional[dict]]):
    DUPLEX_OPTS = [("Simple", ""), ("+", "+"), ("-", "-"), ("Split", "split")]
    TONE_OPTS = [
        ("Off", ""), ("Tone (TX)", "Tone"),
        ("TSQL (RX)", "TSQL"), ("DTCS", "DTCS"), ("Cross", "Cross")
    ]
    MODE_OPTS = [("FM", "FM"), ("NFM", "NFM")]
    POWER_OPTS = [("High (5W)", "High"), ("Med (3W)", "Med"), ("Low (1W)", "Low")]
    SKIP_OPTS = [("No", ""), ("Si", "S")]

    def __init__(self, channel: chirp_common.Memory):
        super().__init__()
        self.mem = channel
        self.ch_number = channel.number
        self.result: Optional[dict] = None

    def compose(self):
        m = self.mem
        freq = f"{m.freq / 1e6:.4f}" if m.freq else ""
        off = f"{m.offset / 1e6:.4f}" if m.offset else "0"
        if m.tmode == "Tone":
            tone_freq = str(m.rtone) if m.rtone and m.rtone > 0 else "88.5"
        else:
            tone_freq = str(m.ctone) if m.ctone and m.ctone > 0 else "88.5"

        with Vertical():
            yield Label(f"Editar Canal {m.number}", id="edit-title")
            yield Label("Nombre:", classes="field-label")
            yield Input(value=m.name.strip(), id="name", max_length=8)
            yield Label("Frecuencia (MHz):", classes="field-label")
            yield Input(value=freq, id="freq")
            yield Label("Duplex:", classes="field-label")
            yield Select(self.DUPLEX_OPTS, value=m.duplex or "", id="duplex")
            yield Label("Offset (MHz):", classes="field-label")
            yield Input(value=off, id="offset")
            yield Label("Tono:", classes="field-label")
            yield Select(self.TONE_OPTS, value=m.tmode or "", id="tmode")
            yield Label("Tono CTCSS:", classes="field-label")
            yield Input(value=tone_freq, id="tonefreq")
            yield Label("Modo:", classes="field-label")
            yield Select(self.MODE_OPTS, value=m.mode or "FM", id="mode")
            yield Label("Potencia:", classes="field-label")
            pw = str(m.power) if m.power else "Low"
            yield Select(self.POWER_OPTS, value=pw, id="power")
            yield Label("Skip:", classes="field-label")
            yield Select(self.SKIP_OPTS, value=m.skip or "", id="skip")
            with Horizontal(classes="button-row"):
                yield Button("Guardar", id="save", variant="primary")
                yield Button("Cancelar", id="cancel")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "save":
            try:
                d = {}
                d["name"] = self.query_one("#name", Input).value.strip()[:8]

                freq_str = self.query_one("#freq", Input).value.strip()
                try:
                    d["freq"] = float(freq_str) * 1_000_000
                except ValueError:
                    raise ValueError("Frecuencia invalida")

                d["duplex"] = self.query_one("#duplex", Select).value or ""

                off_str = self.query_one("#offset", Input).value.strip()
                try:
                    d["offset"] = float(off_str) * 1_000_000 if off_str else 0
                except ValueError:
                    raise ValueError("Offset invalido")

                d["tmode"] = self.query_one("#tmode", Select).value or ""

                tf = self.query_one("#tonefreq", Input).value.strip()
                try:
                    d["tonefreq"] = float(tf) if tf else 88.5
                except ValueError:
                    raise ValueError("Tono CTCSS invalido")

                d["mode"] = self.query_one("#mode", Select).value or "FM"
                d["power_label"] = self.query_one("#power", Select).value or "Low"
                d["skip"] = self.query_one("#skip", Select).value or ""
                d["ch"] = self.ch_number

                self.result = d
                self.dismiss(self.result)
            except ValueError as e:
                self.app.push_screen(AlertScreen("Error", str(e)))
        else:
            self.dismiss(None)


class ProgressScreen(ModalScreen):
    def __init__(self, title: str = ""):
        super().__init__()
        self._title = title

    def compose(self):
        with Vertical():
            yield Label(self._title, id="prog-title")
            yield Label("", id="prog-msg")
            yield ProgressBar(total=100, show_eta=False, id="prog-bar")

    def update(self, cur: int, max_val: int, msg: str):
        self.query_one("#prog-msg", Label).update(msg)
        bar = self.query_one("#prog-bar", ProgressBar)
        bar.total = max_val if max_val > 0 else 100
        bar.progress = cur


class MainScreen(Screen):
    BINDINGS = [
        Binding("d", "download", "Descargar"),
        Binding("u", "upload", "Subir"),
        Binding("e", "edit", "Editar"),
        Binding("a", "add", "Agregar"),
        Binding("delete", "delete", "Borrar"),
        Binding("i", "import_csv", "Import CSV"),
        Binding("x", "export_csv", "Export CSV"),
        Binding("o", "open_img", "Abrir .img"),
        Binding("s", "save_img", "Guardar .img"),
        Binding("v", "verify", "Verificar"),
        Binding("c", "clear_all", "Limpiar"),
        Binding("r", "refresh", "Refrescar"),
        Binding("q", "quit", "Salir"),
    ]

    COLUMNS = ["CH", "Nombre", "Frec MHz", "Tono", "Modo", "Pot", "Skip"]
    COL_FREQ = 2
    COL_TONE = 3
    COL_MODE = 4
    COL_POWER = 5
    COL_SKIP = 6

    def __init__(self):
        super().__init__()
        self.row_keys: list = []

    def compose(self):
        with Vertical():
            yield Header()
            yield DataTable(id="dt", cursor_type="row")
            yield Label("", id="status", classes="status-bar")
            yield Footer()

    def on_mount(self):
        table = self.query_one("#dt", DataTable)
        table.add_columns(*self.COLUMNS)
        self._refresh_status()
        self._load_default_img()

    def _load_default_img(self):
        app = self.app
        if os.path.exists(DEFAULT_BACKUP) and not app.channels:
            try:
                radio = UV9R(DEFAULT_BACKUP)
                app.channels = collect_radio_channels(radio)
                app.mmap_bytes = radio.get_mmap()
                app.source = os.path.basename(DEFAULT_BACKUP)
                app.dirty = False
                self._rebuild_table()
            except Exception:
                pass

    def _rebuild_table(self):
        table = self.query_one("#dt", DataTable)
        table.clear()
        self.row_keys.clear()
        for mem in self.app.channels:
            if mem.empty:
                continue
            rk = table.add_row(
                str(mem.number),
                mem.name.strip()[:9] if mem.name else "",
                f"{mem.freq / 1e6:.4f}" if mem.freq else "",
                self._tone_str(mem),
                mem.mode or "FM",
                str(mem.power) if mem.power else "",
                "S" if mem.skip == "S" else "",
                key=str(mem.number),
            )
            self.row_keys.append(rk)
        self._refresh_status()

    def _tone_str(self, m):
        if m.tmode == "Tone":
            return f"T{m.rtone}"
        if m.tmode == "TSQL":
            return f"SQL{m.ctone}"
        if m.tmode == "DTCS":
            return f"D{m.dtcs}"
        if m.tmode == "Cross":
            return f"C {m.cross_mode}"
        return ""

    def _refresh_status(self):
        app = self.app
        parts = [f"Fuente: {app.source or 'Sin datos'}"]
        if app.dirty:
            parts.append(" [Modificado]")
        n = sum(1 for m in app.channels if not m.empty)
        parts.append(f"  Canales: {n}")
        st = self.query_one("#status", Label)
        st.update(" | ".join(parts))

    def _get_selected_ch(self):
        table = self.query_one("#dt", DataTable)
        if not self.row_keys or table.cursor_row is None:
            return None
        if table.cursor_row >= len(self.row_keys):
            return None
        rk = self.row_keys[table.cursor_row]
        return int(str(rk))

    # --- actions ---

    def action_download(self):
        if self.app.dirty:
            self.push_screen(
                ConfirmScreen("Confirmar", "Hay cambios sin guardar. Descargar igual?"),
                self._do_download
            )
        else:
            self._do_download(True)

    def _do_download(self, confirmed):
        if not confirmed:
            return
        if not self.app.port:
            self.app.port = find_port()
        if not self.app.port:
            self.push_screen(AlertScreen("Error", "No se detecta el radio. Conecte el cable USB."))
            return
        self._prog_screen = ProgressScreen("Descargando del radio...")
        self.push_screen(self._prog_screen)
        self._run_download()

    @work(thread=True, exclusive=True)
    def _run_download(self):
        try:
            radio, ser = setup_radio(self.app.port)

            def progress_cb(s):
                self.call_from_thread(self._update_progress, s.cur, s.max, s.msg)

            radio.status_fn = progress_cb
            radio.sync_in()
            channels = collect_radio_channels(radio)
            mmap = radio.get_mmap()
            ser.close()
            self.call_from_thread(self._download_done, channels, mmap)
        except Exception as e:
            self.call_from_thread(self._radio_error, str(e))

    def _update_progress(self, cur, max_val, msg):
        ps = getattr(self, '_prog_screen', None)
        if ps:
            ps.update(cur, max_val, msg)

    def _download_done(self, channels, mmap):
        self._prog_screen = None
        self.app.channels = channels
        self.app.mmap_bytes = mmap
        self.app.source = "Radio"
        self.app.dirty = False
        self._rebuild_table()
        self.pop_screen()
        self.push_screen(
            AlertScreen("Completado", "Descarga desde el radio exitosa")
        )

    def _radio_error(self, msg):
        ps = getattr(self, '_prog_screen', None)
        if ps:
            self._prog_screen = None
            try:
                ps.dismiss(None)
            except Exception:
                pass
        self.push_screen(AlertScreen("Error de Radio", msg))

    def action_upload(self):
        if not self.app.channels or not self.app.mmap_bytes:
            self.push_screen(AlertScreen("Error", "No hay datos para subir. Descargue o abra un archivo primero."))
            return
        if not self.app.port:
            self.app.port = find_port()
        if not self.app.port:
            self.push_screen(AlertScreen("Error", "No se detecta el radio."))
            return
        self.push_screen(
            ConfirmScreen("Confirmar", "Subir datos al radio? Se sobrescribiran los datos actuales."),
            self._do_upload
        )

    def _do_upload(self, confirmed):
        if not confirmed:
            return
        self._prog_screen = ProgressScreen("Subiendo al radio...")
        self.push_screen(self._prog_screen)
        self._run_upload()

    @work(thread=True, exclusive=True)
    def _run_upload(self):
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".img", delete=False)
            try:
                tmp.write(self.app.mmap_bytes)
                fname = tmp.name
            finally:
                tmp.close()

            radio, ser = setup_radio(self.app.port)

            def progress_cb(s):
                self.call_from_thread(self._update_progress, s.cur, s.max, s.msg)

            radio.load_mmap(fname)
            radio.status_fn = progress_cb

            for mem in self.app.channels:
                radio.set_memory(mem)

            radio.sync_out()
            ser.close()
            os.unlink(fname)
            self.call_from_thread(self._upload_done)
        except Exception as e:
            self.call_from_thread(self._radio_error, str(e))

    def _upload_done(self):
        self._prog_screen = None
        self.app.dirty = False
        self._refresh_status()
        self.pop_screen()
        self.push_screen(AlertScreen("Completado", "Subida al radio exitosa"))

    def action_edit(self):
        ch_idx = self._get_selected_ch()
        if ch_idx is None:
            return
        mem = self.app.channels[ch_idx]
        self.push_screen(EditChannel(mem), self._edit_done)

    def _edit_done(self, result):
        if result is None:
            return
        ch_idx = int(result.get("ch", 0))
        mem = self.app.channels[ch_idx]
        mem.name = result["name"]
        mem.freq = int(result["freq"])
        mem.duplex = result["duplex"]
        mem.offset = int(result["offset"])
        mem.tmode = result["tmode"]
        mem.mode = result["mode"]
        mem.empty = False
        mem.skip = "S" if result["skip"] == "S" else ""

        tf = result["tonefreq"]
        if result["tmode"] in ("Tone",):
            mem.rtone = tf
            mem.ctone = 88.5
        elif result["tmode"] in ("TSQL",):
            mem.ctone = tf
            mem.rtone = 88.5
        elif result["tmode"] == "DTCS":
            mem.dtcs = int(tf) if tf else 23
            mem.dtcs_polarity = "NN"
        elif result["tmode"] == "Cross":
            mem.rtone = tf
            mem.ctone = tf
            mem.cross_mode = "Tone->Tone"
        else:
            mem.rtone = 88.5
            mem.ctone = 88.5

        pw_label = result["power_label"]
        for pl in POWER_LEVELS:
            if str(pl) == pw_label:
                mem.power = pl
                break
        if not mem.power:
            mem.power = POWER_LEVELS[-1]

        self.app.dirty = True
        self._rebuild_table()

    def action_add(self):
        if not self.app.channels:
            self.app.channels = [chirp_common.Memory() for _ in range(128)]
            for i, m in enumerate(self.app.channels):
                m.number = i
                m.empty = True
            self.app.mmap_bytes = None

        idx = None
        for i, m in enumerate(self.app.channels):
            if m.empty:
                idx = i
                break
        if idx is None:
            self.push_screen(AlertScreen("Error", "Todos los canales estan ocupados"))
            return

        mem = chirp_common.Memory()
        mem.number = idx
        mem.freq = 146520000
        mem.name = ""
        mem.duplex = ""
        mem.offset = 0
        mem.tmode = ""
        mem.rtone = 88.5
        mem.ctone = 88.5
        mem.mode = "FM"
        mem.power = POWER_LEVELS[-1]
        mem.skip = ""
        mem.empty = False
        self.app.channels[idx] = mem

        self.app.dirty = True
        self._rebuild_table()
        self.push_screen(EditChannel(mem), self._edit_done)

    def action_delete(self):
        ch_idx = self._get_selected_ch()
        if ch_idx is None:
            return
        mem = self.app.channels[ch_idx]
        if mem.empty:
            return
        name = mem.name.strip() or f"CH{ch_idx}"
        self.push_screen(
            ConfirmScreen("Borrar", f"Borrar canal {ch_idx} ({name})?"),
            lambda ok, idx=ch_idx: self._do_delete(ok, idx)
        )

    def _do_delete(self, confirmed, ch_idx):
        if not confirmed:
            return
        mem = chirp_common.Memory()
        mem.number = ch_idx
        mem.empty = True
        self.app.channels[ch_idx] = mem
        self.app.dirty = True
        self._rebuild_table()

    def action_import_csv(self):
        self.push_screen(
            InputScreen("Importar CSV", "Ruta del CSV:",
                        value=DEFAULT_CSV),
            self._do_import_csv
        )

    def _do_import_csv(self, path):
        if not path:
            return
        if not os.path.exists(path):
            self.push_screen(AlertScreen("Error", f"Archivo no encontrado: {path}"))
            return
        try:
            rows = csv_rows(path)
        except Exception as e:
            self.push_screen(AlertScreen("Error", f"No se pudo leer CSV: {e}"))
            return

        if not self.app.channels:
            self.app.channels = [chirp_common.Memory() for _ in range(128)]
            for i, m in enumerate(self.app.channels):
                m.number = i
                m.empty = True

        imported = 0
        for row in rows:
            loc = int(row.get("Location", 0))
            if loc < 0 or loc >= 128:
                continue
            name = row.get("Name", "").strip()
            freq_mhz = float(row.get("Frequency", 0))
            if freq_mhz == 0:
                continue

            mem = chirp_common.Memory()
            mem.number = loc
            mem.freq = int(freq_mhz * 1_000_000)
            mem.name = name
            mem.duplex = row.get("Duplex", "").strip()
            mem.offset = int(float(row.get("Offset", 0)) * 1_000_000)
            mem.tmode = row.get("Tone", "").strip()
            mem.rtone = float(row.get("rToneFreq", "88.5"))
            mem.ctone = float(row.get("cToneFreq", "88.5"))
            mem.mode = row.get("Mode", "FM").strip() or "FM"
            mem.skip = "S" if row.get("Skip", "").strip() == "S" else ""
            mem.empty = False

            power_w = float(row.get("Power", 1))
            target_dbm = 10.0 * math.log10(power_w * 1000.0)
            best = POWER_LEVELS[0]
            for pl in POWER_LEVELS:
                if abs(float(pl) - target_dbm) < abs(float(best) - target_dbm):
                    best = pl
            mem.power = best

            self.app.channels[loc] = mem
            imported += 1

        self.app.dirty = True
        if not self.app.source:
            self.app.source = "CSV"
        self._rebuild_table()
        self.push_screen(AlertScreen("Importado", f"{imported} canales importados desde CSV"))

    def action_export_csv(self):
        if not self.app.channels:
            self.push_screen(AlertScreen("Error", "No hay canales para exportar"))
            return
        self.push_screen(
            InputScreen("Exportar CSV", "Ruta de salida:",
                        value=os.path.join(DRIVER_DIR, "export.csv")),
            self._do_export_csv
        )

    def _do_export_csv(self, path):
        if not path:
            return
        non_empty = [m for m in self.app.channels if not m.empty]
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["Location", "Name", "Frequency", "Duplex", "Offset",
                           "Tone", "rToneFreq", "cToneFreq", "Mode", "Power", "Skip"])
                for m in non_empty:
                    w.writerow([
                        m.number, m.name, f"{m.freq / 1e6:.4f}",
                        m.duplex if m.duplex else "",
                        f"{m.offset / 1e6:.4f}",
                        m.tmode or "",
                        m.rtone if m.rtone > 0 else "",
                        m.ctone if m.ctone > 0 else "",
                        m.mode,
                        f"{float(m.power):.2f}" if m.power else "",
                        "S" if m.skip == "S" else "",
                    ])
            self.push_screen(AlertScreen("Exportado", f"{len(non_empty)} canales exportados a {path}"))
        except Exception as e:
            self.push_screen(AlertScreen("Error", f"No se pudo exportar: {e}"))

    def action_open_img(self):
        self.push_screen(
            InputScreen("Abrir .img", "Ruta del archivo .img:", value=DEFAULT_BACKUP),
            self._do_open_img
        )

    def _do_open_img(self, path):
        if not path:
            return
        if not os.path.exists(path):
            self.push_screen(AlertScreen("Error", f"Archivo no encontrado: {path}"))
            return
        try:
            radio = UV9R(path)
            self.app.channels = collect_radio_channels(radio)
            self.app.mmap_bytes = radio.get_mmap()
            self.app.source = os.path.basename(path)
            self.app.dirty = False
            self._rebuild_table()
            self.push_screen(AlertScreen("Abierto", f"Cargado: {path}"))
        except Exception as e:
            self.push_screen(AlertScreen("Error", f"No se pudo abrir: {e}"))

    def action_save_img(self):
        if not self.app.channels or self.app.mmap_bytes is None:
            self.push_screen(AlertScreen("Error", "No hay datos para guardar"))
            return
        self.push_screen(
            InputScreen("Guardar .img", "Ruta de salida:",
                        value=os.path.join(DRIVER_DIR, "uv9r_editado.img")),
            self._do_save_img
        )

    def _do_save_img(self, path):
        if not path:
            return
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".img", delete=False)
            try:
                tmp.write(self.app.mmap_bytes)
                fname = tmp.name
            finally:
                tmp.close()

            radio = UV9R(fname)
            for mem in self.app.channels:
                radio.set_memory(mem)
            radio.save_mmap(path)
            os.unlink(fname)

            self.app.mmap_bytes = radio.get_mmap()
            self.app.source = os.path.basename(path)
            self.app.dirty = False
            self._refresh_status()
            self.push_screen(AlertScreen("Guardado", f"Imagen guardada: {path}"))
        except Exception as e:
            self.push_screen(AlertScreen("Error", f"No se pudo guardar: {e}"))

    def action_verify(self):
        if not self.app.port:
            self.app.port = find_port()
        if not self.app.port:
            self.push_screen(AlertScreen("Error", "No se detecta el radio."))
            return
        self.push_screen(
            InputScreen("Verificar", "Ruta del CSV de referencia:",
                        value=DEFAULT_CSV),
            self._do_verify
        )

    def _do_verify(self, csv_path):
        if not csv_path:
            return
        if not os.path.exists(csv_path):
            self.push_screen(AlertScreen("Error", f"CSV no encontrado: {csv_path}"))
            return
        try:
            rows = csv_rows(csv_path)
        except Exception as e:
            self.push_screen(AlertScreen("Error", str(e)))
            return

        expected = {}
        for row in rows:
            loc = int(row.get("Location", 0))
            expected[loc] = row

        self._prog_screen = ProgressScreen("Verificando...")
        self.push_screen(self._prog_screen)
        self._run_verify(csv_path, expected)

    @work(thread=True, exclusive=True)
    def _run_verify(self, csv_path, expected):
        try:
            radio, ser = setup_radio(self.app.port)

            def progress_cb(s):
                self.call_from_thread(self._update_progress, s.cur, s.max, s.msg)

            radio.status_fn = progress_cb
            radio.sync_in()

            errors_list = []
            checked = 0
            for loc, row in expected.items():
                mem = radio.get_memory(loc)
                if mem.empty:
                    errors_list.append(f"CH{loc}: vacio (esperado {row.get('Name')})")
                    continue
                checked += 1
                act_freq = mem.freq / 1e6
                exp_freq = float(row.get("Frequency", 0))
                if abs(act_freq - exp_freq) > 0.001:
                    errors_list.append(f"CH{loc}: freq {act_freq:.4f} != {exp_freq:.4f}")
                act_name = mem.name.strip()
                exp_name = row.get("Name", "").strip()
                if act_name != exp_name:
                    errors_list.append(f"CH{loc}: nombre '{act_name}' != '{exp_name}'")

            ser.close()
            self.call_from_thread(self._verify_done, errors_list, checked)
        except Exception as e:
            self.call_from_thread(self._radio_error, str(e))

    def _verify_done(self, errors_list, checked):
        self._prog_screen = None
        self.pop_screen()
        if not errors_list:
            self.push_screen(AlertScreen("Verificacion", f"OK: {checked} canales coinciden con CSV"))
        else:
            msg = "\n".join(errors_list[:10])
            if len(errors_list) > 10:
                msg += f"\n... y {len(errors_list) - 10} mas"
            try:
                self.push_screen(AlertScreen(f"Errores ({len(errors_list)})", msg))
            except Exception:
                pass

    def action_clear_all(self):
        if not self.app.channels:
            return
        n = sum(1 for m in self.app.channels if not m.empty)
        if n == 0:
            return
        self.push_screen(
            ConfirmScreen("Limpiar", f"Borrar todos los {n} canales?"),
            self._do_clear_all
        )

    def _do_clear_all(self, confirmed):
        if not confirmed:
            return
        for i, m in enumerate(self.app.channels):
            m.empty = True
            m.name = ""
        self.app.dirty = True
        self._rebuild_table()

    def action_refresh(self):
        self._rebuild_table()

    def action_quit(self):
        self.app.exit()


class BaofengApp(App):
    CSS = TUI_CSS

    def __init__(self):
        super().__init__()
        self.channels: list = []
        self.mmap_bytes: Optional[bytes] = None
        self.port: Optional[str] = None
        self.source: str = ""
        self.dirty: bool = False

    def on_mount(self):
        self.push_screen(MainScreen())


def run_tui():
    BaofengApp().run()


if __name__ == "__main__":
    run_tui()
