#!/usr/bin/env python3
import os
import sys
import json
import subprocess
import threading
from datetime import datetime

from gi import require_version
require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib  # type: ignore

# -------------------------------------------------------
# Basis-Pfade & Logging
# -------------------------------------------------------

HOME = os.path.expanduser("~")
DATA_DIR = os.path.join(HOME, ".local", "share", "camwall")
os.makedirs(DATA_DIR, exist_ok=True)

RECORDER_LOG = os.path.join(DATA_DIR, "camwall-recorder.log")


def log(msg: str) -> None:
    """Einfaches Log in camwall-recorder.log."""
    os.makedirs(os.path.dirname(RECORDER_LOG), exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    try:
        with open(RECORDER_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        # Logging darf niemals das Programm killen
        pass


# -------------------------------------------------------
# Config laden (nutzt modules.config_loader)
# -------------------------------------------------------

def load_camwall_config():
    """
    Lädt die Camwall-Konfiguration über modules.config_loader.load_config(),
    damit Recorder & GUI dieselbe config.json nutzen.
    """
    try:
        from modules.config_loader import load_config  # type: ignore
    except Exception as e:
        log(f"FEHLER: modules.config_loader konnte nicht importiert werden: {e}")
        return {}

    try:
        cfg = load_config()
        streams = cfg.get("streams", {})
        monitors = cfg.get("monitors", {})
        log(
            "Config geladen (monitors="
            f"{list(monitors.keys())}, streams={list(streams.keys())})"
        )
        return cfg
    except Exception as e:
        log(f"FEHLER: load_config() schlug fehl: {e}")
        return {}


# -------------------------------------------------------
# GTK-GUI
# -------------------------------------------------------

class CamwallRecorderWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Camwall Recorder")
        self.set_default_size(480, 220)

        self.config = load_camwall_config()
        self.streams = self.config.get("streams", {})

        # UI-Struktur
        outer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        outer_box.set_border_width(8)
        self.add(outer_box)

        # --- Zeile 1: Stream-Auswahl ---
        row_stream = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        outer_box.pack_start(row_stream, False, False, 0)

        lbl_stream = Gtk.Label(label="Stream:", xalign=0.0)
        row_stream.pack_start(lbl_stream, False, False, 0)

        self.stream_store = Gtk.ListStore(str, str)  # id, name
        self._fill_stream_store()

        self.combo_stream = Gtk.ComboBox.new_with_model(self.stream_store)
        renderer_text = Gtk.CellRendererText()
        self.combo_stream.pack_start(renderer_text, True)
        self.combo_stream.add_attribute(renderer_text, "text", 1)
        if len(self.stream_store) > 0:
            self.combo_stream.set_active(0)
        row_stream.pack_start(self.combo_stream, True, True, 0)

        # --- Zeile 2: Titel der Aufnahme ---
        row_title = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        outer_box.pack_start(row_title, False, False, 0)

        lbl_title = Gtk.Label(label="Titel:", xalign=0.0)
        row_title.pack_start(lbl_title, False, False, 0)

        self.entry_title = Gtk.Entry()
        self.entry_title.set_placeholder_text("Optional: Titel für die Aufnahme")
        row_title.pack_start(self.entry_title, True, True, 0)

        # --- Zeile 3: Buttons ---
        row_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        outer_box.pack_start(row_buttons, False, False, 4)

        self.btn_record = Gtk.Button(label="Aufnahme starten")
        self.btn_record.connect("clicked", self.on_record_clicked)
        row_buttons.pack_start(self.btn_record, True, True, 0)

        self.btn_stop = Gtk.Button(label="Aufnahme stoppen")
        self.btn_stop.connect("clicked", self.on_stop_clicked)
        row_buttons.pack_start(self.btn_stop, True, True, 0)

        self.btn_screenshot = Gtk.Button(label="Screenshot")
        self.btn_screenshot.connect("clicked", self.on_screenshot_clicked)
        row_buttons.pack_start(self.btn_screenshot, True, True, 0)

        # --- Zeile 4: Status ---
        self.lbl_status = Gtk.Label(label="Bereit.")
        outer_box.pack_start(self.lbl_status, False, False, 4)

        # Fenster-Schließen
        self.connect("destroy", Gtk.main_quit)

    # -------------------------
    # Hilfsfunktionen
    # -------------------------

    def _fill_stream_store(self):
        """Befüllt die ComboBox mit Einträgen aus config['streams']."""
        self.stream_store.clear()
        if not self.streams:
            return
        # Sortieren nach Anzeigenamen
        items = []
        for sid, sconf in self.streams.items():
            name = sconf.get("name", sid)
            items.append((sid, name))
        items.sort(key=lambda x: x[1].lower())
        for sid, name in items:
            self.stream_store.append([sid, name])

    def _get_selected_stream_id(self):
        """Liefert die stream_id aus der ComboBox oder None."""
        tree_iter = self.combo_stream.get_active_iter()
        if tree_iter is None:
            return None
        model = self.combo_stream.get_model()
        stream_id = model[tree_iter][0]
        return stream_id

    def _set_status(self, text: str):
        self.lbl_status.set_text(text)
        log(f"STATUS: {text}")

    # -------------------------
    # Button-Callbacks
    # -------------------------

    def on_record_clicked(self, button):
        stream_id = self._get_selected_stream_id()
        if not stream_id or stream_id not in self.streams:
            self._set_status("Bitte zuerst einen Stream auswählen.")
            return

        sconf = self.streams[stream_id]
        url = sconf.get("url")
        browser = sconf.get("browser", "firefox")

        # Titel bestimmen
        title_text = self.entry_title.get_text().strip()
        if not title_text:
            # Standard: Stream-Name + Zeitstempel
            base_name = sconf.get("name", stream_id).replace(" ", "_")
            title_text = base_name

        self._set_status("Starte Aufnahme …")

        def worker():
            cmd = [
                sys.executable,
                "-m",
                "modules.stream_recorder",
                "record",
                url,
                title_text,
                browser,
            ]
            log(f"Starte Aufnahme: cmd={cmd}")
            try:
                proc = subprocess.run(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                )
                log(f"record stdout:\n{proc.stdout}\n---")
                log(f"record stderr:\n{proc.stderr}\n---")
                if proc.returncode == 0:
                    GLib.idle_add(
                        self._set_status,
                        "Aufnahme gestartet (siehe recordings-Ordner).",
                    )
                else:
                    GLib.idle_add(
                        self._set_status,
                        "Fehler beim Start der Aufnahme (Details im Log).",
                    )
            except Exception as e:
                log(f"FEHLER bei record: {e}")
                GLib.idle_add(
                    self._set_status,
                    f"Fehler beim Start der Aufnahme: {e}",
                )

        threading.Thread(target=worker, daemon=True).start()

    def on_stop_clicked(self, button):
        self._set_status("Stoppe Aufnahme …")

        def worker():
            cmd = [
                sys.executable,
                "-m",
                "modules.stream_recorder",
                "stop",
            ]
            log(f"Stoppe Aufnahme: cmd={cmd}")
            try:
                proc = subprocess.run(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                )
                log(f"stop stdout:\n{proc.stdout}\n---")
                log(f"stop stderr:\n{proc.stderr}\n---")
                GLib.idle_add(
                    self._set_status,
                    "Aufnahme gestoppt (oder es lief keine Aufnahme).",
                )
            except Exception as e:
                log(f"FEHLER bei stop: {e}")
                GLib.idle_add(
                    self._set_status,
                    f"Fehler beim Stoppen der Aufnahme: {e}",
                )

        threading.Thread(target=worker, daemon=True).start()

    def on_screenshot_clicked(self, button):
        stream_id = self._get_selected_stream_id()
        if not stream_id or stream_id not in self.streams:
            self._set_status("Bitte zuerst einen Stream auswählen.")
            return

        sconf = self.streams[stream_id]
        url = sconf.get("url")
        browser = sconf.get("browser", "firefox")

        # Titel für Screenshot (optional: eigener Text + Timestamp)
        base_name = sconf.get("name", stream_id).replace(" ", "_")
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        shot_title = f"{base_name}_{ts}"

        self._set_status("Screenshot wird erstellt …")

        # WICHTIG: Screenshot in eigenem Thread, damit GUI nicht einfriert
        def worker():
            cmd = [
                sys.executable,
                "-m",
                "modules.stream_recorder",
                "shot",
                url,
                shot_title,
                browser,
            ]
            log(f"Screenshot-Process starten: cmd={cmd}")
            try:
                proc = subprocess.run(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                )
                log(f"shot stdout:\n{proc.stdout}\n---")
                log(f"shot stderr:\n{proc.stderr}\n---")
                if proc.returncode == 0:
                    # Versuchen, Dateipfad aus stdout zu extrahieren
                    # (modules.stream_recorder gibt z.B. 'Screenshot erstellt: <pfad>' aus)
                    out = proc.stdout.strip()
                    msg = "Screenshot erstellt."
                    for line in out.splitlines():
                        if "Screenshot erstellt:" in line:
                            msg = line.strip()
                            break
                    GLib.idle_add(self._set_status, msg)
                else:
                    GLib.idle_add(
                        self._set_status,
                        "Screenshot fehlgeschlagen (Details im Log).",
                    )
            except Exception as e:
                log(f"FEHLER bei shot: {e}")
                GLib.idle_add(
                    self._set_status,
                    f"Fehler beim Screenshot: {e}",
                )

        threading.Thread(target=worker, daemon=True).start()


# -------------------------------------------------------
# main()
# -------------------------------------------------------

def main():
    win = CamwallRecorderWindow()
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
