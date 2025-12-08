#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import subprocess
from pathlib import Path
from datetime import datetime
import warnings

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib

# ---------------------------------------------------------------------------
# Pfade & Modul-Imports
# ---------------------------------------------------------------------------

BASE_APP_DIR = Path(__file__).resolve().parent
if str(BASE_APP_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_APP_DIR))

try:
    from modules.config_loader import load_config
    from modules import stream_recorder
except Exception as e:
    print("Fehler beim Import der Camwall-Module:", e, file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

BASE_DIR = Path.home() / ".local" / "share" / "camwall"
OVERLAY_LOG = BASE_DIR / "overlay.log"


def log(msg: str) -> None:
    try:
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        with OVERLAY_LOG.open("a", encoding="utf-8") as f:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Helfer: Stream / Monitor
# ---------------------------------------------------------------------------

def _safe_title_for_filename(title: str) -> str:
    base = (
        title.strip()
        .replace(" ", "_")
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
    cleaned = "".join(ch for ch in base if ch in allowed)
    return cleaned or "aufnahme"


def get_monitor_and_stream(config, monitor_id: str):
    monitors = config.get("monitors", {})
    streams = config.get("streams", {})

    mconf = monitors.get(monitor_id)
    if not mconf:
        raise RuntimeError(f"Monitor '{monitor_id}' ist in der Konfiguration nicht vorhanden.")

    stream_id = mconf.get("stream_id", "none")
    if not stream_id or stream_id == "none":
        raise RuntimeError(
            f"Für Monitor „{mconf.get('name', monitor_id)}“ ist kein Stream zugewiesen."
        )

    sconf = streams.get(stream_id)
    if not sconf:
        raise RuntimeError(
            f"Der Stream '{stream_id}' ist in der Konfiguration nicht vorhanden."
        )

    return mconf, sconf


def build_record_params(config, monitor_id: str):
    mconf, sconf = get_monitor_and_stream(config, monitor_id)
    stype = sconf.get("type", "direct")
    url = (sconf.get("url") or "").strip()
    if not url:
        raise RuntimeError("Für den ausgewählten Stream ist keine URL hinterlegt.")

    browser = None
    if stype == "youtube_cookies":
        browser = sconf.get("browser") or "firefox"

    monitor_name = mconf.get("name", monitor_id)
    stream_name = sconf.get("name", "")
    base_title = f"{monitor_name}_{stream_name}" if stream_name else monitor_name
    title = _safe_title_for_filename(base_title)

    return url, browser, title


def get_monitor_rect_for_id(monitor_id: str):
    """
    Liefert eine Gdk.Rectangle für 'left' / 'right' / Sonstiges.
    'left'  -> Monitor mit kleinstem X
    'right' -> Monitor mit größtem X
    andere  -> Primärmonitor (oder linker, wenn Primär nicht verfügbar)
    """
    display = Gdk.Display.get_default()
    if not display:
        log("get_monitor_rect_for_id: kein Display gefunden")
        return None

    n = display.get_n_monitors()
    if n <= 0:
        log("get_monitor_rect_for_id: keine Monitore gefunden")
        return None

    monitors = []
    for i in range(n):
        mon = display.get_monitor(i)
        rect = mon.get_geometry()
        monitors.append((i, rect))

    monitors.sort(key=lambda item: item[1].x)
    log(
        "get_monitor_rect_for_id: Monitore (index, x, y, w, h)="
        + str([(i, r.x, r.y, r.width, r.height) for i, r in monitors])
    )

    if monitor_id == "left":
        _, rect = monitors[0]
        log(f"get_monitor_rect_for_id: benutze linken Monitor (x={rect.x})")
        return rect
    elif monitor_id == "right":
        _, rect = monitors[-1]
        log(f"get_monitor_rect_for_id: benutze rechten Monitor (x={rect.x})")
        return rect
    else:
        primary = display.get_primary_monitor()
        if primary is not None:
            rect = primary.get_geometry()
            log(f"get_monitor_rect_for_id: benutze Primärmonitor (x={rect.x})")
            return rect
        _, rect = monitors[0]
        log(f"get_monitor_rect_for_id: benutze Fallback (linker Monitor, x={rect.x})")
        return rect


# ---------------------------------------------------------------------------
# Overlay-Fenster + Controller
# ---------------------------------------------------------------------------

class OverlayHoverController:
    def __init__(
        self,
        window: Gtk.Window,
        normal_opacity: float = 0.35,
        hover_opacity: float = 0.95,
        step: float = 0.1,
        interval_ms: int = 30,
    ):
        self.window = window
        self.normal_opacity = normal_opacity
        self.hover_opacity = hover_opacity
        self.step = step
        self.interval_ms = interval_ms
        self.hover_count = 0
        self.target_opacity = normal_opacity
        self._animation_source_id = None
        self._current_opacity = normal_opacity

    def set_initial_opacity(self):
        self._current_opacity = self.normal_opacity
        self._set_opacity_safe(self._current_opacity)

    def on_mouse_enter(self, widget, event):
        if getattr(event, "detail", None) == Gdk.NotifyType.INFERIOR:
            return False
        self.hover_count += 1
        self._set_target(self.hover_opacity)
        return False

    def on_mouse_leave(self, widget, event):
        if getattr(event, "detail", None) == Gdk.NotifyType.INFERIOR:
            return False
        self.hover_count = max(0, self.hover_count - 1)
        if self.hover_count == 0:
            self._set_target(self.normal_opacity)
        return False

    def _set_target(self, opacity: float):
        self.target_opacity = opacity
        if self._animation_source_id is None:
            self._animation_source_id = GLib.timeout_add(
                self.interval_ms, self._animate_step
            )

    def _animate_step(self):
        delta = self.target_opacity - self._current_opacity
        if abs(delta) <= self.step:
            self._current_opacity = self.target_opacity
            self._set_opacity_safe(self._current_opacity)
            self._animation_source_id = None
            return False

        self._current_opacity += self.step if delta > 0 else -self.step
        self._set_opacity_safe(self._current_opacity)
        return True

    def _set_opacity_safe(self, value: float):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                self.window.set_opacity(value)
        except Exception as e:
            log(f"Warnung: set_opacity fehlgeschlagen: {e}")


class OverlayRecorderController:
    def __init__(self, monitor_id: str):
        self.monitor_id = monitor_id
        self.is_recording = False
        self._sync_state_from_active_recording()

    def _sync_state_from_active_recording(self):
        try:
            active = stream_recorder._read_active_recording()  # type: ignore[attr-defined]
        except Exception:
            active = None
        self.is_recording = bool(active)

    def start_recording(self):
        config = load_config()
        url, browser, title = build_record_params(config, self.monitor_id)
        log(
            f"Overlay: starte Aufnahme – monitor={self.monitor_id}, "
            f"url={url}, browser={browser}, title={title}"
        )
        meta = stream_recorder.start_recording(url, title, browser)
        log(f"Overlay: Aufnahme gestartet: {meta}")
        self.is_recording = True
        return meta

    def stop_recording(self):
        log("Overlay: stoppe Aufnahme …")
        ok = stream_recorder.stop_recording()
        if ok:
            log("Overlay: Aufnahme gestoppt.")
        else:
            log("Overlay: stop_recording meldet: keine aktive Aufnahme.")
        self.is_recording = False
        return ok

    def take_screenshot(self):
        config = load_config()
        url, browser, title = build_record_params(config, self.monitor_id)
        log(
            f"Overlay: Screenshot – monitor={self.monitor_id}, "
            f"url={url}, browser={browser}, title={title}"
        )
        path = stream_recorder.take_screenshot(url, title, browser)
        log(f"Overlay: Screenshot erstellt: {path}")
        return path

    def refresh_background(self):
        log(f"Overlay: Refresh für Monitor {self.monitor_id} ausgelöst.")
        subprocess.Popen(
            ["/usr/bin/env", "python3", "/opt/camwall/camwall-apply.py"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


class OverlayWindow(Gtk.Window):
    def __init__(self, monitor_id: str = "right"):
        super().__init__(title="Camwall Recorder")
        self.monitor_id = monitor_id

        # Controller
        self.hover_controller = OverlayHoverController(self)
        self.recorder_controller = OverlayRecorderController(monitor_id)

        # Fenster-Style: mit Titelleiste, aber immer oben / nicht in Taskleiste
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)

        # Normales kleines Fenster
        self.set_default_size(260, 70)
        self.set_resizable(False)
        self.set_position(Gtk.WindowPosition.CENTER)

        # Fenster-Icon (falls vorhanden)
        try:
            Gtk.Window.set_default_icon_name("camwall")
        except Exception:
            pass

        # Layout
        root_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        root_box.set_border_width(8)
        self.add(root_box)

        # Statuslabel
        self.label_status = Gtk.Label()
        self.label_status.set_xalign(0)
        root_box.pack_start(self.label_status, True, True, 0)

        # Button-Leiste
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        root_box.pack_start(btn_box, False, False, 0)

        # Aufnahme starten
        self.btn_record = Gtk.Button()
        img_rec = Gtk.Image.new_from_icon_name("media-record", Gtk.IconSize.BUTTON)
        self.btn_record.set_image(img_rec)
        self.btn_record.set_always_show_image(True)
        self.btn_record.set_tooltip_text("Aufnahme für den aktuellen Monitor-Stream starten.")
        self.btn_record.connect("clicked", self.on_record_clicked)
        btn_box.pack_start(self.btn_record, False, False, 0)

        # Aufnahme stoppen
        self.btn_stop = Gtk.Button()
        img_stop = Gtk.Image.new_from_icon_name("media-playback-stop", Gtk.IconSize.BUTTON)
        self.btn_stop.set_image(img_stop)
        self.btn_stop.set_always_show_image(True)
        self.btn_stop.set_tooltip_text("Laufende Aufnahme stoppen.")
        self.btn_stop.connect("clicked", self.on_stop_clicked)
        btn_box.pack_start(self.btn_stop, False, False, 0)

        # Screenshot
        self.btn_shot = Gtk.Button()
        img_shot = Gtk.Image.new_from_icon_name("camera-photo", Gtk.IconSize.BUTTON)
        self.btn_shot.set_image(img_shot)
        self.btn_shot.set_always_show_image(True)
        self.btn_shot.set_tooltip_text("Screenshot des aktuellen Monitor-Streams erstellen.")
        self.btn_shot.connect("clicked", self.on_shot_clicked)
        btn_box.pack_start(self.btn_shot, False, False, 0)

        # Refresh-Button
        self.btn_refresh = Gtk.Button()
        img_ref = Gtk.Image.new_from_icon_name("view-refresh", Gtk.IconSize.BUTTON)
        self.btn_refresh.set_image(img_ref)
        self.btn_refresh.set_always_show_image(True)
        self.btn_refresh.set_tooltip_text(
            "Stream-Hintergrund für diesen Monitor neu starten (Refresh)."
        )
        self.btn_refresh.connect("clicked", self.on_refresh_clicked)
        btn_box.pack_start(self.btn_refresh, False, False, 0)

        # Rechtsklick -> kleines Menü
        self.connect("button-press-event", self.on_button_press_event)

        # Mouseover für Transparenz: direkt auf dem Fenster (inkl. Titelleiste)
        self.add_events(
            Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK
        )
        self.connect("enter-notify-event", self.hover_controller.on_mouse_enter)
        self.connect("leave-notify-event", self.hover_controller.on_mouse_leave)

        self.connect("destroy", Gtk.main_quit)

        self._update_status_label()
        self.show_all()

        # Direkt nach dem Anzeigen: auf Zielmonitor schieben und transparent machen
        GLib.idle_add(self._position_and_set_opacity)

    # ------------------------------------------------------------------
    # Positionierung + initiale Transparenz
    # ------------------------------------------------------------------

    def _position_and_set_opacity(self):
        try:
            rect = get_monitor_rect_for_id(self.monitor_id)
            if rect is None:
                log("_position_and_set_opacity: keine Monitor-Rect, zentriere Fenster.")
                self.set_position(Gtk.WindowPosition.CENTER)
            else:
                self.show_all()
                win_w, win_h = self.get_size()
                margin = 20
                pos_x = rect.x + rect.width - win_w - margin
                pos_y = rect.y + rect.height - win_h - margin
                self.move(pos_x, pos_y)
                log(
                    f"Overlay positioniert für monitor_id='{self.monitor_id}' "
                    f"bei x={pos_x}, y={pos_y}, mon_rect=({rect.x},{rect.y},{rect.width},{rect.height})"
                )

            self.hover_controller.set_initial_opacity()

        except Exception as e:
            log(f"_position_and_set_opacity: Fehler: {e}")
            self.set_position(Gtk.WindowPosition.CENTER)
        return False  # nur einmal ausführen

    # ------------------------------------------------------------------
    # Status / Buttons
    # ------------------------------------------------------------------

    def _update_status_label(self, extra: str = ""):
        try:
            config = load_config()
            monitors = config.get("monitors", {})
            mconf = monitors.get(self.monitor_id, {})
            monitor_name = mconf.get("name", self.monitor_id)
        except Exception:
            monitor_name = self.monitor_id

        rec_text = (
            "Aufnahme: an" if self.recorder_controller.is_recording else "Aufnahme: aus"
        )
        txt = f"{monitor_name} – {rec_text}"
        if extra:
            txt += f" ({extra})"
        self.label_status.set_text(txt)

        self.btn_record.set_sensitive(not self.recorder_controller.is_recording)
        self.btn_stop.set_sensitive(self.recorder_controller.is_recording)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def on_button_press_event(self, widget, event):
        if event.type == Gdk.EventType.BUTTON_PRESS and event.button == 3:
            menu = self.build_context_menu()
            menu.show_all()
            menu.popup_at_pointer(event)
        return False

    def build_context_menu(self):
        menu = Gtk.Menu()

        item_lock = Gtk.MenuItem(label="Overlay sperren")
        item_lock.connect("activate", lambda *_: self._lock_overlay())
        menu.append(item_lock)

        item_unlock = Gtk.MenuItem(label="Overlay entsperren")
        item_unlock.connect("activate", lambda *_: self._unlock_overlay())
        menu.append(item_unlock)

        transparency_menu = Gtk.Menu()
        item_trans = Gtk.MenuItem(label="Transparenz")
        item_trans.set_submenu(transparency_menu)
        menu.append(item_trans)

        for label, value in [
            ("Niedrig (0.20)", 0.20),
            ("Mittel (0.35)", 0.35),
            ("Hoch (0.60)", 0.60),
            ("Sehr hoch (0.95)", 0.95),
        ]:
            mi = Gtk.MenuItem(label=label)
            mi.connect("activate", lambda *_ , v=value: self._set_opacity_profile(v))
            transparency_menu.append(mi)

        item_switch = Gtk.MenuItem(label="Monitor wechseln")
        item_switch.connect("activate", lambda *_: self._on_switch_monitor())
        menu.append(item_switch)

        item_open_recordings = Gtk.MenuItem(label="Recording-Ordner öffnen")
        item_open_recordings.connect(
            "activate",
            lambda *_: subprocess.Popen(
                ["xdg-open", str(Path("~/.local/share/camwall/recordings").expanduser())]
            ),
        )
        menu.append(item_open_recordings)

        item_probe_stream = Gtk.MenuItem(label="Stream-URL neu ermitteln")
        item_probe_stream.connect("activate", lambda *_: self._probe_stream_url())
        menu.append(item_probe_stream)

        item_show_log = Gtk.MenuItem(label="Logdatei anzeigen")
        item_show_log.connect(
            "activate", lambda *_: subprocess.Popen(["xdg-open", str(OVERLAY_LOG)])
        )
        menu.append(item_show_log)

        item_reload = Gtk.MenuItem(label="Overlay neu laden")
        item_reload.connect("activate", lambda *_: self._reload_overlay())
        menu.append(item_reload)

        item_reposition = Gtk.MenuItem(label="Neu positionieren")
        item_reposition.connect("activate", lambda *_: self._position_and_set_opacity())
        menu.append(item_reposition)

        item_debug = Gtk.MenuItem(label="Debug Info zeigen")
        item_debug.connect("activate", lambda *_: self._show_debug_info())
        menu.append(item_debug)

        item_quit = Gtk.MenuItem(label="Overlay schließen")
        item_quit.connect("activate", lambda *_: self.destroy())
        menu.append(item_quit)

        return menu

    def switch_monitor(self, new_monitor_id: str):
        log(f"Overlay: Monitorwechsel zu '{new_monitor_id}'")

        self.monitor_id = new_monitor_id
        self.recorder_controller.monitor_id = new_monitor_id

        self._position_and_set_opacity()
        self._update_status_label("Monitor gewechselt")

    def _on_switch_monitor(self):
        new_id = "left" if self.monitor_id == "right" else "right"
        self.switch_monitor(new_id)

    def _lock_overlay(self):
        log("Overlay: sperre Fenster-Dekoration.")
        try:
            self.set_decorated(False)
        except Exception as e:
            log(f"Overlay: Fehler beim Sperren: {e}")
            self._show_error_dialog(str(e))

    def _unlock_overlay(self):
        log("Overlay: entsperre Fenster-Dekoration.")
        try:
            self.set_decorated(True)
        except Exception as e:
            log(f"Overlay: Fehler beim Entsperren: {e}")
            self._show_error_dialog(str(e))

    def _set_opacity_profile(self, value: float):
        log(f"Overlay: setze Transparenz-Profil auf {value}")
        self.hover_controller.normal_opacity = value
        self.hover_controller.hover_opacity = 0.95
        self.hover_controller.set_initial_opacity()
    def _probe_stream_url(self):
        try:
            config = load_config()
            _, sconf = get_monitor_and_stream(config, self.monitor_id)
            stype = sconf.get("type", "direct")
            url = (sconf.get("url") or "").strip()
            if not url:
                raise RuntimeError("Für den ausgewählten Stream ist keine URL hinterlegt.")

            if stype in ("youtube", "youtube_cookies"):
                log(f"Overlay: ermittele Stream-URL via yt-dlp für Typ '{stype}'")
                result = subprocess.check_output(["yt-dlp", "-g", url], text=True)
                stream_url = result.strip().splitlines()[0] if result else ""
                if not stream_url:
                    raise RuntimeError("yt-dlp lieferte keine URL.")
                self._show_info_dialog(f"Ermittelte Stream-URL:\n{stream_url}")
            else:
                self._show_info_dialog(
                    f"Stream-Typ: {stype}\nKonfigurierte URL:\n{url}"
                )
        except Exception as e:
            log(f"Overlay: Fehler beim Ermitteln der Stream-URL: {e}")
            self._show_error_dialog(str(e))

    def _reload_overlay(self):
        log("Overlay: neu laden")
        try:
            current_monitor = self.monitor_id
            self.destroy()
            subprocess.Popen(["camwall-overlay", current_monitor])
        except Exception as e:
            log(f"Overlay: Fehler beim Neu-Laden: {e}")
            self._show_error_dialog(str(e))

    # ------------------------------------------------------------------
    # Button-Aktionen
    # ------------------------------------------------------------------

    def on_record_clicked(self, button):
        try:
            self.recorder_controller.start_recording()
            self._update_status_label("gestartet")
        except Exception as e:
            log(f"Overlay: Fehler beim Start der Aufnahme: {e}")
            self._show_error_dialog(str(e))

    def on_stop_clicked(self, button):
        try:
            ok = self.recorder_controller.stop_recording()
            if ok:
                self._update_status_label("gestoppt")
            else:
                self._update_status_label("keine aktiv")
        except Exception as e:
            log(f"Overlay: Fehler beim Stoppen der Aufnahme: {e}")
            self._show_error_dialog(str(e))

    def on_shot_clicked(self, button):
        try:
            path = self.recorder_controller.take_screenshot()
            self._update_status_label("Screenshot OK")
            self._show_info_dialog(f"Screenshot erstellt:\n{path}")
        except Exception as e:
            log(f"Overlay: Fehler beim Screenshot: {e}")
            self._show_error_dialog(str(e))

    def on_refresh_clicked(self, button):
        try:
            self.recorder_controller.refresh_background()
            self._update_status_label("Refresh")
        except Exception as e:
            log(f"Overlay: Fehler beim Refresh: {e}")
            self._show_error_dialog(
                "Der Stream konnte nicht neu gestartet werden.\n"
                f"Fehler: {e}"
            )

    # ------------------------------------------------------------------
    # Dialog-Helfer (modernes GTK-API)
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

    def _show_debug_info(self):
        info = (
            f"Monitor: {self.monitor_id}\n"
            f"Recording: {self.recorder_controller.is_recording}\n"
            f"Opacity: {self.hover_controller._current_opacity:.2f}"
        )
        self._show_info_dialog(info)


# Kompatibilität
RecorderOverlayWindow = OverlayWindow


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    monitor_id = "right"
    if len(sys.argv) >= 2:
        monitor_id = sys.argv[1]

    log(f"Starte Overlay für Monitor '{monitor_id}'")
    win = RecorderOverlayWindow(monitor_id=monitor_id)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
