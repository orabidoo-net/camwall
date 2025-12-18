#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import subprocess
from pathlib import Path
from datetime import datetime

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from modules.paths import CONFIG_PATH
from modules.runtime_guard import runtime_summary, in_repo_but_not_running_repo_gui, show_gtk_warning

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_DIR = Path.home() / ".local" / "share" / "camwall"
LOG_FILE = LOG_DIR / "camwall-gui.log"


def log(msg: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        # GUI muss weiterlaufen, auch wenn Logging fehlschlägt
        pass


from modules.controllers import StreamController, MonitorController, RecorderController
from modules.services import ConfigService, MediaService, PreviewService

# Tab-Module
from modules.tabs.monitor_tab import MonitorTab
from modules.tabs.stream_tab import StreamTab
from modules.tabs.recorder_tab import RecorderTab

# Cleanup optional importieren (für .mp4.part Aufräumfunktion)
try:
    from modules.cleanup import cleanup_recordings
except Exception:
    def cleanup_recordings():
        log("Warnung: cleanup_recordings konnte nicht importiert werden.")
        return [], 0


def human_readable_size(num_bytes: int) -> str:
    """Dateigröße hübsch formatieren."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"


def _resolve_apply_target() -> list[str]:
    """
    Liefert einen startbaren Command für camwall-apply.
    Bevorzugt: Repo-local camwall-apply.py, sonst /usr/local/bin/camwall-apply,
    sonst /opt/camwall/camwall-apply.py.
    """
    candidates = [
        Path(__file__).resolve().with_name("camwall-apply.py"),
        Path("/usr/local/bin/camwall-apply"),
        Path("/opt/camwall/camwall-apply.py"),
    ]
    apply_path = next((p for p in candidates if p.exists()), None)
    if not apply_path:
        raise FileNotFoundError("Kein camwall-apply gefunden.")

    if apply_path.suffix == ".py":
        return [sys.executable, str(apply_path)]
    return [str(apply_path)]


# ---------------------------------------------------------------------------
# Dialoge – Stream hinzufügen/bearbeiten
# ---------------------------------------------------------------------------

class StreamEditDialog(Gtk.Dialog):
    """Dialog zum Hinzufügen / Bearbeiten eines Streams."""

    def __init__(self, parent, stream_id=None, stream_conf=None):
        title = "Stream bearbeiten" if stream_id else "Neuen Stream hinzufügen"
        super().__init__(title=title, transient_for=parent, flags=Gtk.DialogFlags.MODAL)

        self.set_default_size(520, 260)
        self.set_border_width(10)

        self.stream_id = stream_id

        box = self.get_content_area()
        box.set_spacing(8)

        grid = Gtk.Grid(column_spacing=8, row_spacing=8, margin=5)
        box.add(grid)

        # Name
        lbl_name = Gtk.Label(label="Name:", xalign=0)
        self.entry_name = Gtk.Entry()
        self.entry_name.set_tooltip_text("Anzeigename für den Stream, z. B. 'Santa Village'.")
        grid.attach(lbl_name, 0, 0, 1, 1)
        grid.attach(self.entry_name, 1, 0, 1, 1)

        # URL
        lbl_url = Gtk.Label(label="URL:", xalign=0)
        self.entry_url = Gtk.Entry()
        self.entry_url.set_tooltip_text("YouTube-URL oder direkte Stream-URL (HLS/MJPEG usw.).")
        grid.attach(lbl_url, 0, 1, 1, 1)
        grid.attach(self.entry_url, 1, 1, 1, 1)

        # Typ
        lbl_type = Gtk.Label(label="Typ:", xalign=0)
        self.combo_type = Gtk.ComboBoxText()
        self.combo_type.append("direct", "Direkte URL (HLS/MJPEG usw.)")
        self.combo_type.append("youtube", "YouTube (ohne Cookies)")
        self.combo_type.append("youtube_cookies", "YouTube (mit Browser-Cookies)")
        self.combo_type.set_tooltip_text(
            "Stream-Typ auswählen. Für Santa-Cam oder Hush Bar z. B. 'YouTube (mit Browser-Cookies)'."
        )
        grid.attach(lbl_type, 0, 2, 1, 1)
        grid.attach(self.combo_type, 1, 2, 1, 1)

        # Browser (nur bei youtube_cookies)
        lbl_browser = Gtk.Label(label="Browser (für Cookies):", xalign=0)
        self.entry_browser = Gtk.Entry()
        self.entry_browser.set_placeholder_text("z. B. firefox, chrome, chromium")
        self.entry_browser.set_tooltip_text(
            "Nur relevant für YouTube (mit Cookies). Name des Browsers (firefox/chromium usw.)"
        )
        grid.attach(lbl_browser, 0, 3, 1, 1)
        grid.attach(self.entry_browser, 1, 3, 1, 1)

        # Buttons
        self.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        self.add_button("Speichern", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)

        # Vorhandene Werte laden
        if stream_conf:
            self.entry_name.set_text(stream_conf.get("name", ""))
            self.entry_url.set_text(stream_conf.get("url", ""))
            stype = stream_conf.get("type", "direct")
            if stype not in ("direct", "youtube", "youtube_cookies"):
                stype = "direct"
            self.combo_type.set_active_id(stype)
            browser = stream_conf.get("browser", "")
            self.entry_browser.set_text(browser)
        else:
            self.combo_type.set_active_id("youtube_cookies")

        self.show_all()

    def get_values(self):
        name = self.entry_name.get_text().strip()
        url = self.entry_url.get_text().strip()
        stype = self.combo_type.get_active_id() or "direct"
        browser = self.entry_browser.get_text().strip()

        return {
            "name": name,
            "url": url,
            "type": stype,
            "browser": browser,
        }


# ---------------------------------------------------------------------------
# Hauptfenster
# ---------------------------------------------------------------------------

class CamwallMainWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Camwall – Live-Stream Wallpaper")
        self.set_default_size(1100, 600)
        self.set_border_width(10)
        self.set_position(Gtk.WindowPosition.CENTER)

        # Icon laden
        try:
            Gtk.Window.set_default_icon_name("camwall")
        except Exception:
            pass

        # Services
        self.config_service = ConfigService()
        media_service = MediaService(cleanup_func=cleanup_recordings)
        preview_service = PreviewService(logger=log)

        # Konfiguration laden
        self.config = self.config_service.config
        self.streams = self.config_service.get_streams()
        self.monitors = self.config_service.get_monitors()

        log("=== GUI-Start ===")
        log(f"CONFIG_PATH = {CONFIG_PATH}")
        log(f"config['monitors'] = {self.monitors}")
        log(f"streams keys = {list(self.streams.keys())}")

        self.log = log
        self.human_readable_size = human_readable_size
        self.StreamEditDialog = StreamEditDialog

        # Controller-Layer
        self.stream_controller = StreamController(self, self.config_service, preview_service)
        self.monitor_controller = MonitorController(self, self.config_service)
        self.recorder_controller = RecorderController(self, media_service)

        # Dictionaries für Widgets
        self.monitor_combo_widgets = {}
        self.monitor_overlay_check_widgets = {}

        # Grundlayout
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(outer)

        header = Gtk.Label(label="<b>Camwall – Live-Stream Hintergründe</b>", use_markup=True)
        header.set_xalign(0)
        outer.pack_start(header, False, False, 0)

        sub = Gtk.Label(label="Verwalte Bildschirm-Hintergründe, Streams und Aufnahmen.", xalign=0)
        outer.pack_start(sub, False, False, 0)

        # Notebook (Tabs)
        notebook = Gtk.Notebook()
        outer.pack_start(notebook, True, True, 0)

        notebook.append_page(MonitorTab(self), Gtk.Label(label="Bildschirm-Hintergründe"))
        notebook.append_page(StreamTab(self), Gtk.Label(label="Stream-Verwaltung"))
        notebook.append_page(RecorderTab(self), Gtk.Label(label="Aufnahme & Screenshots"))

        # Statuszeile
        self.status_label = Gtk.Label(xalign=0)
        self.status_label.set_margin_top(4)
        self._set_status("Bereit.")
        outer.pack_start(self.status_label, False, False, 0)

        # Untere Buttons
        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        outer.pack_start(action_box, False, False, 0)

        action_box.pack_start(Gtk.Label(), True, True, 0)

        btn_exit = Gtk.Button(label="Beenden")
        btn_exit_icon = Gtk.Image.new_from_icon_name("application-exit", Gtk.IconSize.BUTTON)
        btn_exit.set_image(btn_exit_icon)
        btn_exit.set_always_show_image(True)
        btn_exit.set_tooltip_text("Fenster schließen (ohne erneut Anwenden auszulösen).")

        btn_apply = Gtk.Button(label="Anwenden")
        btn_apply_icon = Gtk.Image.new_from_icon_name("emblem-ok", Gtk.IconSize.BUTTON)
        btn_apply.set_image(btn_apply_icon)
        btn_apply.set_always_show_image(True)
        btn_apply.set_tooltip_text("Änderungen speichern und Live-Hintergründe aktualisieren.")

        btn_exit.connect("clicked", self.on_exit_clicked)
        btn_apply.connect("clicked", self.on_apply_clicked)

        action_box.pack_start(btn_exit, False, False, 0)
        action_box.pack_start(btn_apply, False, False, 0)

        self.connect("destroy", Gtk.main_quit)
        self.show_all()

    # ------------------------------------------------------------------
    # Status-Helfer
    # ------------------------------------------------------------------

    def _set_status(self, text: str):
        log(f"STATUS: {text}")
        if hasattr(self, "status_label") and self.status_label is not None:
            self.status_label.set_text(text)

    def _fill_monitor_combo(self, combo: Gtk.ComboBoxText, current_id: str) -> None:
        if not current_id:
            current_id = "none"

        model = combo.get_model()
        if model is not None:
            while len(model) > 0:
                combo.remove(0)

        combo.append("none", "(kein Stream)")

        id_name_pairs = [(sid, sconf.get("name", sid)) for sid, sconf in self.streams.items()]
        id_name_pairs.sort(key=lambda x: x[1].lower())

        for sid, name in id_name_pairs:
            combo.append(sid, name)

        effective_id = current_id if current_id in self.streams or current_id == "none" else "none"
        combo.set_active_id(effective_id)
        log(f"_fill_monitor_combo: requested={current_id}, effective={effective_id}")

    def _refresh_monitor_combos(self) -> None:
        for _mon_id, combo in self.monitor_combo_widgets.items():
            prev_id = combo.get_active_id() or "none"
            self._fill_monitor_combo(combo, prev_id)

    # ------------------------------------------------------------------
    # Apply / Refresh
    # ------------------------------------------------------------------

    def _run_apply(self, monitor_id: str | None = None) -> None:
        cmd = _resolve_apply_target()
        if monitor_id:
            cmd = [*cmd, monitor_id]
        log(f"Starte camwall-apply: {cmd}")
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def refresh_wallpapers(self, monitor_id: str | None = None) -> None:
        """Manuelles Refresh (Monitor-spezifisch oder alle)."""
        try:
            self._run_apply(monitor_id)
            if monitor_id:
                self._set_status(f"Refresh ausgelöst – {monitor_id} wird neu gestartet …")
            else:
                self._set_status("Refresh ausgelöst – Hintergründe werden neu gestartet …")
        except Exception as e:
            log(f"Refresh fehlgeschlagen: {e}")
            self._show_error_dialog(f"Refresh fehlgeschlagen:\n{e}")

    # ------------------------------------------------------------------
    # Overlay-Status
    # ------------------------------------------------------------------

    def _overlay_running(self, mon_id: str) -> bool:
        """
        Prüft, ob bereits ein Overlay-Prozess für mon_id läuft.
        Robust gegen Wrapper (camwall-overlay) und direkte Python-Aufrufe (camwall-overlay.py).
        """
        lines: list[str] = []
        for pat in ("camwall-overlay", "camwall-overlay.py"):
            try:
                out = subprocess.check_output(["pgrep", "-fa", pat], text=True)
                if out:
                    lines.extend(out.splitlines())
            except subprocess.CalledProcessError:
                pass
            except Exception as e:
                log(f"_overlay_running: pgrep Fehler ({pat}): {e}")

        if not lines:
            return False

        # Match: mon_id als Argument (grob, aber zuverlässig genug)
        needle = f" {mon_id}"
        for line in lines:
            if needle in line or line.rstrip().endswith(mon_id):
                return True
        return False

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------

    def on_exit_clicked(self, _button):
        self._set_status("Beenden.")
        self.destroy()

    def _refresh_rec_stream_combo(self) -> None:
        """Füllt/aktualisiert die Stream-Auswahlliste im Recorder-Tab."""
        combo = getattr(self, "rec_stream_combo", None)
        if combo is None:
            return

        prev_id = None
        try:
            if combo.get_active() >= 0:
                prev_id = combo.get_active_id()
        except Exception:
            prev_id = None

        # vorhandene Einträge löschen
        model = combo.get_model()
        if model is not None:
            try:
                while len(model) > 0:
                    combo.remove(0)
            except Exception:
                pass

        combo.append("", "Bitte Stream wählen …")

        streams = getattr(self, "streams", {}) or {}
        pairs = [(sid, conf.get("name", sid)) for sid, conf in streams.items()]
        pairs.sort(key=lambda x: x[1].lower())

        for sid, name in pairs:
            combo.append(sid, name)

        if prev_id and prev_id in streams:
            combo.set_active_id(prev_id)
        else:
            combo.set_active(0)

    def on_apply_clicked(self, _button):
        log("Anwenden geklickt")

        # Snapshot: vorherige Stream-Zuordnung (für per-monitor Restart)
        old_monitors = dict(self.monitors or {})

        # Monitore speichern (und changes ermitteln)
        changed_monitors: list[str] = []

        for mon_id, combo in self.monitor_combo_widgets.items():
            active_id = combo.get_active_id()
            new_sid = active_id if active_id and active_id != "none" else "none"

            old_sid = (old_monitors.get(mon_id, {}) or {}).get("stream_id", "none")

            overlay_flag = False
            chk = self.monitor_overlay_check_widgets.get(mon_id)
            if chk is not None:
                overlay_flag = bool(chk.get_active())

            # schreiben
            self.monitor_controller.assign_stream(mon_id, new_sid, overlay_flag)

            # nur Stream-Änderung triggert Restart
            if old_sid != new_sid:
                changed_monitors.append(mon_id)

        # Konfiguration speichern
        self.config["streams"] = self.streams
        self.monitor_controller.save_monitors()
        self.monitors = self.config_service.get_monitors()

        # Nur betroffene Monitore neu starten
        try:
            if changed_monitors:
                for mid in changed_monitors:
                    self._run_apply(mid)
                self._set_status(f"Angewendet – neu gestartet: {', '.join(changed_monitors)}")
            else:
                self._set_status("Angewendet – keine Stream-Änderung an Monitoren.")
                log("on_apply_clicked: keine Stream-Änderung → kein Wallpaper-Restart")
        except Exception as e:
            log(f"Fehler beim Start von camwall-apply: {e}")
            self._show_error_dialog(
                "Konfiguration gespeichert,\n"
                "aber camwall-apply konnte nicht gestartet werden.\n\n"
                f"Fehler: {e}"
            )
            return

        # Overlay-Autostart (optional) – aber NICHT doppelt starten
        for mon_id, mconf in (self.monitors or {}).items():
            if mconf.get("overlay_autostart"):
                if self._overlay_running(mon_id):
                    log(f"Overlay läuft bereits für Monitor {mon_id} – starte nicht erneut.")
                    continue
                try:
                    subprocess.Popen(
                        ["camwall-overlay", mon_id],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    log(f"Overlay-Autostart für Monitor {mon_id} ausgelöst.")
                except Exception as e:
                    log(f"Fehler beim Start von camwall-overlay ({mon_id}): {e}")

        # WICHTIG: GUI bleibt offen (kein self.destroy())

    # ------------------------------------------------------------------
    # Hilfsdialoge (modernes GTK-API)
    # ------------------------------------------------------------------

    def _show_error_dialog(self, text: str):
        dlg = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=text,
        )
        dlg.run()
        dlg.destroy()

    def _show_info_dialog(self, text: str):
        dlg = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=text,
        )
        dlg.run()
        dlg.destroy()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    try:
        summary = runtime_summary()
        if in_repo_but_not_running_repo_gui(summary):
            show_gtk_warning(summary)
    except Exception:
        pass

    win = CamwallMainWindow()
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
