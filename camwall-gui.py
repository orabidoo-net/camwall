#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import subprocess
from pathlib import Path
from datetime import datetime

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk

from modules.paths import CONFIG_PATH
from modules.runtime_guard import runtime_summary, in_repo_but_not_running_repo_gui, show_gtk_warning

# ---------------------------------------------------------------------------
# Logging & Status-Dateien
# ---------------------------------------------------------------------------

LOG_DIR = Path.home() / ".local" / "share" / "camwall"
LOG_FILE = LOG_DIR / "camwall-gui.log"
APPLY_LOG = LOG_DIR / "camwall.log"
RUN_FILE = Path("/tmp/camwall_active") 

def log(msg: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass

from modules.controllers import StreamController, MonitorController, RecorderController
from modules.services import ConfigService, MediaService, PreviewService

from modules.tabs.monitor_tab import MonitorTab
from modules.tabs.stream_tab import StreamTab
from modules.tabs.recorder_tab import RecorderTab
from modules.tabs.schedule_tab import ScheduleTab  # <--- HIER NEU IMPORTIERT

try:
    from modules.cleanup import cleanup_recordings
except Exception:
    def cleanup_recordings():
        return [], 0

def human_readable_size(num_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"

def _resolve_apply_target() -> list[str]:
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

def _resolve_overlay_target() -> list[str]:
    candidates = [
        Path(__file__).resolve().with_name("camwall-overlay.py"),
        Path(__file__).resolve().with_name("camwall-overlay"),
        Path("/usr/local/bin/camwall-overlay"),
        Path("/opt/camwall/camwall-overlay.py"),
    ]
    overlay_path = next((p for p in candidates if p.exists()), None)
    if not overlay_path:
        return ["camwall-overlay"]
    if overlay_path.suffix == ".py":
        return [sys.executable, str(overlay_path)]
    return [str(overlay_path)]

# ---------------------------------------------------------------------------
# CSS Styling
# ---------------------------------------------------------------------------
def apply_css():
    css = b"""
    window {
        background-color: #f3f4f6;
    }
    notebook {
        background-color: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
    }
    notebook header {
        background-color: #e5e7eb;
    }
    button {
        border-radius: 6px;
        padding: 6px 12px;
        border: 1px solid #d1d5db;
        background-image: none;
        background-color: #ffffff;
        color: #374151;
        transition: all 0.2s ease-in-out;
    }
    button:hover {
        background-color: #f9fafb;
        border-color: #9ca3af;
    }
    button.primary-btn {
        background-color: #3b82f6;
        color: white;
        border: 1px solid #2563eb;
    }
    button.primary-btn:hover {
        background-color: #2563eb;
    }
    button.danger-btn {
        background-color: #ef4444;
        color: white;
        border: 1px solid #dc2626;
    }
    button.danger-btn:hover {
        background-color: #dc2626;
    }
    """
    provider = Gtk.CssProvider()
    provider.load_from_data(css)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )

class StreamEditDialog(Gtk.Dialog):
    def __init__(self, parent, stream_id=None, stream_conf=None):
        title = "Stream bearbeiten" if stream_id else "Neuen Stream hinzufügen"
        super().__init__(title=title, transient_for=parent, flags=Gtk.DialogFlags.MODAL)
        self.set_default_size(520, 340)
        self.set_border_width(10)
        self.stream_id = stream_id

        box = self.get_content_area()
        box.set_spacing(8)
        grid = Gtk.Grid(column_spacing=8, row_spacing=8, margin=5)
        box.add(grid)

        lbl_name = Gtk.Label(label="Name:", xalign=0)
        self.entry_name = Gtk.Entry()
        grid.attach(lbl_name, 0, 0, 1, 1)
        grid.attach(self.entry_name, 1, 0, 1, 1)

        lbl_url = Gtk.Label(label="URL:", xalign=0)
        self.entry_url = Gtk.Entry()
        grid.attach(lbl_url, 0, 1, 1, 1)
        grid.attach(self.entry_url, 1, 1, 1, 1)

        lbl_type = Gtk.Label(label="Typ:", xalign=0)
        self.combo_type = Gtk.ComboBoxText()
        self.combo_type.append("direct", "Direkte URL (HLS/MJPEG usw.)")
        self.combo_type.append("youtube", "YouTube (ohne Cookies)")
        self.combo_type.append("youtube_cookies", "YouTube (mit Browser-Cookies)")
        grid.attach(lbl_type, 0, 2, 1, 1)
        grid.attach(self.combo_type, 1, 2, 1, 1)

        lbl_browser = Gtk.Label(label="Browser (für Cookies):", xalign=0)
        self.entry_browser = Gtk.Entry()
        self.entry_browser.set_placeholder_text("z. B. firefox, chrome, chromium")
        grid.attach(lbl_browser, 0, 3, 1, 1)
        grid.attach(self.entry_browser, 1, 3, 1, 1)

        lbl_location = Gtk.Label(label="Ort (für Wetter):", xalign=0)
        self.entry_location = Gtk.Entry()
        self.entry_location.set_placeholder_text("z. B. Bangkok")
        grid.attach(lbl_location, 0, 4, 1, 1)
        grid.attach(self.entry_location, 1, 4, 1, 1)

        lbl_timezone = Gtk.Label(label="Zeitzone (für Uhrzeit):", xalign=0)
        self.combo_timezone = Gtk.ComboBoxText.new_with_entry()
        
        common_tzs = [
            "America/Los_Angeles",
            "America/New_York",
            "Asia/Bangkok",
            "Asia/Dubai",
            "Asia/Tokyo",
            "Australia/Sydney",
            "Europe/Berlin",
            "Europe/London",
            "Pacific/Honolulu"
        ]
        for tz in common_tzs:
            self.combo_timezone.append_text(tz)
            
        self.combo_timezone.get_child().set_placeholder_text("z. B. Europe/Berlin")
        grid.attach(lbl_timezone, 0, 5, 1, 1)
        grid.attach(self.combo_timezone, 1, 5, 1, 1)

        self.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        self.add_button("Speichern", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)

        if stream_conf:
            self.entry_name.set_text(stream_conf.get("name", ""))
            self.entry_url.set_text(stream_conf.get("url", ""))
            stype = stream_conf.get("type", "direct")
            if stype not in ("direct", "youtube", "youtube_cookies"):
                stype = "direct"
            self.combo_type.set_active_id(stype)
            
            browser = stream_conf.get("browser", "")
            if stype == "youtube_cookies" and not browser:
                browser = "firefox"
            self.entry_browser.set_text(browser)

            self.entry_location.set_text(stream_conf.get("location", ""))
            self.combo_timezone.get_child().set_text(stream_conf.get("timezone", ""))
        else:
            self.combo_type.set_active_id("youtube_cookies")
            self.entry_browser.set_text("firefox")

        self.show_all()

    def get_values(self):
        name = self.entry_name.get_text().strip()
        url = self.entry_url.get_text().strip()
        stype = self.combo_type.get_active_id() or "direct"
        browser = self.entry_browser.get_text().strip()
        location = self.entry_location.get_text().strip()
        timezone = self.combo_timezone.get_child().get_text().strip()

        if stype == "youtube_cookies" and not browser:
            browser = "firefox"

        return {
            "name": name,
            "url": url,
            "type": stype,
            "browser": browser,
            "location": location,
            "timezone": timezone,
        }

class CamwallMainWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Camwall – Live-Stream Wallpaper")
        self.set_default_size(1100, 600)
        self.set_border_width(15) 
        self.set_position(Gtk.WindowPosition.CENTER)
        
        apply_css()

        try:
            Gtk.Window.set_default_icon_name("camwall")
        except Exception:
            pass

        self.config_service = ConfigService()
        media_service = MediaService(cleanup_func=cleanup_recordings)
        preview_service = PreviewService(logger=log)

        self.config = self.config_service.config
        self.streams = self.config_service.get_streams()
        self.monitors = self.config_service.get_monitors()

        self.log = log
        self.human_readable_size = human_readable_size
        self.StreamEditDialog = StreamEditDialog

        self.stream_controller = StreamController(self, self.config_service, preview_service)
        self.monitor_controller = MonitorController(self, self.config_service)
        self.recorder_controller = RecorderController(self, media_service)

        self.monitor_combo_widgets = {}
        self.monitor_overlay_check_widgets = {}

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.add(outer)

        header = Gtk.Label(label="<span size='x-large' weight='bold' color='#1f2937'>Camwall</span> – <span color='#4b5563'>Live-Stream Hintergründe</span>", use_markup=True)
        header.set_xalign(0)
        outer.pack_start(header, False, False, 0)

        notebook = Gtk.Notebook()
        outer.pack_start(notebook, True, True, 0)

        notebook.append_page(MonitorTab(self), Gtk.Label(label="Bildschirme"))
        notebook.append_page(StreamTab(self), Gtk.Label(label="Streams"))
        notebook.append_page(RecorderTab(self), Gtk.Label(label="Media"))
        # <--- HIER WIRD DER NEUE REITER EINGEHÄNGT
        notebook.append_page(ScheduleTab(self), Gtk.Label(label="Zeitplan"))

        self.status_label = Gtk.Label(xalign=0)
        self.status_label.set_margin_top(4)
        self._set_status("Bereit.")
        outer.pack_start(self.status_label, False, False, 0)

        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        outer.pack_start(action_box, False, False, 0)

        btn_log = Gtk.Button(label="Fehler-Log öffnen")
        btn_log_icon = Gtk.Image.new_from_icon_name("text-x-generic", Gtk.IconSize.BUTTON)
        btn_log.set_image(btn_log_icon)
        btn_log.set_always_show_image(True)
        btn_log.set_tooltip_text("Öffnet das Hintergrund-Log, um zu sehen, warum ein Stream nicht startet.")
        btn_log.connect("clicked", self.on_log_clicked)
        action_box.pack_start(btn_log, False, False, 0)

        action_box.pack_start(Gtk.Label(), True, True, 0)

        btn_exit = Gtk.Button(label="Beenden")
        btn_exit.get_style_context().add_class("danger-btn") 
        btn_exit_icon = Gtk.Image.new_from_icon_name("application-exit", Gtk.IconSize.BUTTON)
        btn_exit.set_image(btn_exit_icon)
        btn_exit.set_always_show_image(True)

        btn_apply = Gtk.Button(label="Anwenden")
        btn_apply.get_style_context().add_class("primary-btn") 
        btn_apply_icon = Gtk.Image.new_from_icon_name("emblem-ok", Gtk.IconSize.BUTTON)
        btn_apply.set_image(btn_apply_icon)
        btn_apply.set_always_show_image(True)

        btn_exit.connect("clicked", self.on_exit_clicked)
        btn_apply.connect("clicked", self.on_apply_clicked)

        action_box.pack_end(btn_exit, False, False, 0)
        action_box.pack_end(btn_apply, False, False, 0)

        self.connect("destroy", self.on_destroy)
        self.show_all()

    def _clean_shutdown(self):
        log("Beende CamWall und alle Hintergrundprozesse...")
        try:
            if RUN_FILE.exists():
                RUN_FILE.unlink()
        except Exception:
            pass
            
        try:
            subprocess.run(["pkill", "-f", "xwinwrap"], check=False)
            subprocess.run(["pkill", "-f", "mpv.*googlevideo"], check=False)
            subprocess.run(["pkill", "-f", "mpv.*youtube"], check=False)
            subprocess.run(["pkill", "-f", "camwall-overlay"], check=False)
            subprocess.run(["pkill", "-f", "camwall-apply"], check=False)
        except Exception as e:
            log(f"Fehler beim Beenden: {e}")

    def on_destroy(self, widget):
        self._clean_shutdown()
        Gtk.main_quit()

    def on_exit_clicked(self, _button):
        self._set_status("Beenden.")
        self.destroy()
        
    def on_log_clicked(self, _button):
        try:
            subprocess.Popen(["xdg-open", str(APPLY_LOG)])
            self._set_status("Logdatei geöffnet.")
        except Exception as e:
            self._show_error_dialog(f"Konnte Log nicht öffnen:\n{e}")

    def _set_status(self, text: str):
        if hasattr(self, "status_label") and self.status_label is not None:
            self.status_label.set_markup(f"<span color='#4b5563'>{text}</span>")

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

    def _refresh_monitor_combos(self) -> None:
        for _mon_id, combo in self.monitor_combo_widgets.items():
            prev_id = combo.get_active_id() or "none"
            self._fill_monitor_combo(combo, prev_id)

    def _run_apply(self, monitor_target=None) -> None:
        cmd = _resolve_apply_target()
        if isinstance(monitor_target, list):
            cmd.extend(monitor_target)
        elif monitor_target:
            cmd.append(str(monitor_target))
        log(f"Starte camwall-apply: {cmd}")
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _restart_overlays(self, targets: list[str]) -> None:
        for mon_id in targets:
            mconf = (self.monitors or {}).get(mon_id, {})
            subprocess.run(["pkill", "-f", f"camwall-overlay.*{mon_id}"], check=False)
            if mconf.get("overlay_autostart"):
                try:
                    overlay_cmd = _resolve_overlay_target()
                    overlay_cmd.append(mon_id)
                    subprocess.Popen(overlay_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception as e:
                    log(f"Fehler bei camwall-overlay ({mon_id}): {e}")

    def refresh_wallpapers(self, monitor_id: str | None = None) -> None:
        try:
            RUN_FILE.touch(exist_ok=True)
        except Exception:
            pass
            
        try:
            self.config["streams"] = self.streams
            for mon_id_loop, combo in self.monitor_combo_widgets.items():
                new_sid = combo.get_active_id() or "none"
                overlay_flag = False
                chk = self.monitor_overlay_check_widgets.get(mon_id_loop)
                if chk is not None:
                    overlay_flag = bool(chk.get_active())
                self.monitor_controller.assign_stream(mon_id_loop, new_sid, overlay_flag)
                
            self.monitor_controller.save_monitors()
            self.monitors = self.config_service.get_monitors()

            targets = [monitor_id] if monitor_id else list(self.monitor_combo_widgets.keys())
            if not targets:
                targets = ["left", "right"]

            self._run_apply(targets)
            self._restart_overlays(targets)
            msg = f"Refresh ausgelöst – {monitor_id} wird neu gestartet …" if monitor_id else "Refresh ausgelöst – Hintergründe werden neu gestartet …"
            self._set_status(msg)
        except Exception as e:
            self._show_error_dialog(f"Refresh fehlgeschlagen:\n{e}")

    def _overlay_running(self, mon_id: str) -> bool:
        return False

    def _refresh_rec_stream_combo(self) -> None:
        combo = getattr(self, "rec_stream_combo", None)
        if combo is None: return
        prev_id = None
        try:
            if combo.get_active() >= 0: prev_id = combo.get_active_id()
        except Exception: pass
        model = combo.get_model()
        if model is not None:
            try:
                while len(model) > 0: combo.remove(0)
            except Exception: pass
        combo.append("", "Bitte Stream wählen …")
        streams = getattr(self, "streams", {}) or {}
        pairs = [(sid, conf.get("name", sid)) for sid, conf in streams.items()]
        pairs.sort(key=lambda x: x[1].lower())
        for sid, name in pairs: combo.append(sid, name)
        if prev_id and prev_id in streams: combo.set_active_id(prev_id)
        else: combo.set_active(0)

    def on_apply_clicked(self, _button):
        log("Anwenden geklickt")
        
        try:
            RUN_FILE.touch(exist_ok=True)
        except Exception:
            pass

        changed_monitors: list[str] = []
        for mon_id, combo in self.monitor_combo_widgets.items():
            new_sid = combo.get_active_id() or "none"
            overlay_flag = False
            chk = self.monitor_overlay_check_widgets.get(mon_id)
            if chk is not None:
                overlay_flag = bool(chk.get_active())
            self.monitor_controller.assign_stream(mon_id, new_sid, overlay_flag)
            changed_monitors.append(mon_id) 

        self.config["streams"] = self.streams
        self.monitor_controller.save_monitors()
        self.monitors = self.config_service.get_monitors()

        try:
            self._run_apply(changed_monitors)
            self._restart_overlays(changed_monitors)
            self._set_status("Angewendet – Konfiguration gespeichert und neu gestartet.")
        except Exception as e:
            self._show_error_dialog(f"Fehler: {e}")

    def _show_error_dialog(self, text: str):
        dlg = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK, text=text)
        dlg.run()
        dlg.destroy()

    def _show_info_dialog(self, text: str):
        dlg = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.OK, text=text)
        dlg.run()
        dlg.destroy()

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
