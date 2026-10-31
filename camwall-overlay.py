#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import subprocess
import os
import socket
import json
import time
from pathlib import Path
from datetime import datetime
import warnings
import urllib.request
import urllib.parse
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib

try:
    import cairo
    HAS_CAIRO = True
except ImportError:
    HAS_CAIRO = False

BASE_APP_DIR = Path(__file__).resolve().parent
if str(BASE_APP_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_APP_DIR))

try:
    from modules.config_loader import load_config
    from modules import stream_recorder
except Exception as e:
    print("Fehler beim Import der Camwall-Module:", e, file=sys.stderr)
    sys.exit(1)

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


def _resolve_apply_target() -> list[str]:
    candidates = [
        Path(__file__).resolve().with_name("camwall-apply.py"),
        Path("/usr/local/bin/camwall-apply"),
        Path("/opt/camwall/camwall-apply.py"),
    ]
    apply_path = next((p for p in candidates if p.exists()), None)
    if not apply_path:
        return ["camwall-apply"]
    if apply_path.suffix == ".py":
        return [sys.executable, str(apply_path)]
    return [str(apply_path)]


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
    display = Gdk.Display.get_default()
    if not display:
        return None

    n = display.get_n_monitors()
    if n <= 0:
        return None

    monitors = []
    for i in range(n):
        mon = display.get_monitor(i)
        rect = mon.get_geometry()
        monitors.append((i, rect))

    monitors.sort(key=lambda item: item[1].x)

    if monitor_id == "left":
        _, rect = monitors[0]
        return rect
    elif monitor_id == "right":
        _, rect = monitors[-1]
        return rect
    else:
        primary = display.get_primary_monitor()
        if primary is not None:
            rect = primary.get_geometry()
            return rect
        _, rect = monitors[0]
        return rect


class OverlayHoverController:
    def __init__(self, window: Gtk.Window, normal_opacity: float = 0.35, hover_opacity: float = 0.95, step: float = 0.1, interval_ms: int = 30):
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
            self._animation_source_id = GLib.timeout_add(self.interval_ms, self._animate_step)

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
        except Exception:
            pass


class OverlayRecorderController:
    def __init__(self, monitor_id: str):
        self.monitor_id = monitor_id
        self.is_stopping = False
        self._apply_proc: subprocess.Popen | None = None
        self._sync_state_from_active_recording()

    def _sync_state_from_active_recording(self) -> bool:
        try:
            return bool(stream_recorder.is_recording_active(self.monitor_id))
        except Exception:
            return False

    @property
    def is_recording(self) -> bool:
        if self.is_stopping:
            return False
        return self._sync_state_from_active_recording()

    def start_recording(self):
        config = load_config()
        url, browser, title = build_record_params(config, self.monitor_id)
        meta = stream_recorder.start_recording(url, title, browser, self.monitor_id)
        return meta

    def stop_recording(self):
        self.is_stopping = True
        try:
            return stream_recorder.stop_recording(self.monitor_id)
        finally:
            self.is_stopping = False

    def refresh_background(self):
        # Vorher war hier der Pfad zu camwall-apply.py hart auf
        # /opt/camwall/camwall-apply.py codiert. In der Entwicklungsumgebung
        # (Repo-Checkout) existiert dieser Pfad nicht, wodurch der
        # Refresh-Button im Overlay fehlschlug. _resolve_apply_target()
        # sucht - wie auch in camwall-gui.py und camwall-watchdog.py - erst
        # im Repo-Verzeichnis und fällt erst danach auf die installierten
        # Pfade zurück.
        try:
            Path(f"/tmp/camwall_grace_{self.monitor_id}").touch(exist_ok=True)
        except Exception:
            pass

        if self._apply_proc is not None and self._apply_proc.poll() is None:
            try:
                self._apply_proc.terminate()
                self._apply_proc.wait(timeout=0.5)
            except Exception:
                try:
                    self._apply_proc.kill()
                except Exception:
                    pass

        cmd = _resolve_apply_target()
        cmd.append(self.monitor_id)
        self._apply_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


class OverlayWindow(Gtk.Window):
    def __init__(self, monitor_id: str = "right"):
        super().__init__(title="Camwall Recorder")
        self.monitor_id = monitor_id

        self._blink_timer = None
        self._blink_state = False
        self._displayed_recording_state = False
        self._sync_timer = None

        self.hover_controller = OverlayHoverController(self)
        self.recorder_controller = OverlayRecorderController(monitor_id)

        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)

        self.set_default_size(260, -1)
        self.set_position(Gtk.WindowPosition.CENTER)

        try:
            Gtk.Window.set_default_icon_name("camwall")
        except Exception:
            pass

        main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(main_vbox)

        top_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        top_box.set_border_width(8)
        main_vbox.pack_start(top_box, False, False, 0)

        self.label_status = Gtk.Label()
        self.label_status.set_xalign(0)
        top_box.pack_start(self.label_status, True, True, 0)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        top_box.pack_start(btn_box, False, False, 0)

        self.btn_record = Gtk.Button()
        img_rec = Gtk.Image.new_from_icon_name("media-record", Gtk.IconSize.BUTTON)
        self.btn_record.set_image(img_rec)
        self.btn_record.set_always_show_image(True)
        self.btn_record.set_tooltip_text("Aufnahme starten.")
        self.btn_record.connect("clicked", self.on_record_clicked)
        btn_box.pack_start(self.btn_record, False, False, 0)

        self.btn_stop = Gtk.Button()
        img_stop = Gtk.Image.new_from_icon_name("media-playback-stop", Gtk.IconSize.BUTTON)
        self.btn_stop.set_image(img_stop)
        self.btn_stop.set_always_show_image(True)
        self.btn_stop.set_tooltip_text("Aufnahme stoppen.")
        self.btn_stop.connect("clicked", self.on_stop_clicked)
        btn_box.pack_start(self.btn_stop, False, False, 0)

        self.btn_shot = Gtk.Button()
        img_shot = Gtk.Image.new_from_icon_name("camera-photo", Gtk.IconSize.BUTTON)
        self.btn_shot.set_image(img_shot)
        self.btn_shot.set_always_show_image(True)
        self.btn_shot.set_tooltip_text("Latenzfreien Screenshot (Sofort-Kamera) erstellen.\n(Oder einfach Doppelklick irgendwo ins Overlay!)")
        self.btn_shot.connect("clicked", self.on_shot_clicked)
        btn_box.pack_start(self.btn_shot, False, False, 0)

        self.btn_refresh = Gtk.Button()
        img_ref = Gtk.Image.new_from_icon_name("view-refresh", Gtk.IconSize.BUTTON)
        self.btn_refresh.set_image(img_ref)
        self.btn_refresh.set_always_show_image(True)
        self.btn_refresh.set_tooltip_text("Stream neu laden.")
        self.btn_refresh.connect("clicked", self.on_refresh_clicked)
        btn_box.pack_start(self.btn_refresh, False, False, 0)

        self.btn_audio = Gtk.ToggleButton()
        img_audio = Gtk.Image.new_from_icon_name("audio-volume-muted", Gtk.IconSize.BUTTON)
        self.btn_audio.set_image(img_audio)
        self.btn_audio.set_always_show_image(True)
        self.btn_audio.set_tooltip_text("Ton einschalten")
        self.btn_audio.connect("toggled", self.on_audio_toggled)
        btn_box.pack_start(self.btn_audio, False, False, 0)

        self.btn_info = Gtk.ToggleButton()
        img_info = Gtk.Image.new_from_icon_name("dialog-information", Gtk.IconSize.BUTTON)
        self.btn_info.set_image(img_info)
        self.btn_info.set_always_show_image(True)
        self.btn_info.set_tooltip_text("Lokale Infos anzeigen")
        self.btn_info.connect("toggled", self.on_info_toggled)
        btn_box.pack_start(self.btn_info, False, False, 0)

        self.info_revealer = Gtk.Revealer()
        self.info_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.info_revealer.set_transition_duration(300)
        
        info_panel_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        info_panel_box.set_border_width(8)
        
        self.info_label = Gtk.Label()
        self.info_label.set_use_markup(True)
        self.info_label.set_justify(Gtk.Justification.LEFT)
        self.info_label.set_xalign(0)
        
        info_panel_box.pack_start(self.info_label, True, True, 0)
        self.info_revealer.add(info_panel_box)
        main_vbox.pack_start(self.info_revealer, False, False, 0)

        self.connect("button-press-event", self.on_button_press_event)
        self.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK | Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("enter-notify-event", self.hover_controller.on_mouse_enter)
        self.connect("leave-notify-event", self.hover_controller.on_mouse_leave)

        self.connect("destroy", self._on_destroy)

        self._update_status_label()
        self.show_all()

        GLib.idle_add(self._position_and_set_opacity)
        self._sync_timer = GLib.timeout_add(1000, self._poll_recording_state)


    def _on_destroy(self, *_args):
        if self._sync_timer is not None:
            try:
                GLib.source_remove(self._sync_timer)
            except Exception:
                pass
            self._sync_timer = None
        if self._blink_timer is not None:
            try:
                GLib.source_remove(self._blink_timer)
            except Exception:
                pass
            self._blink_timer = None
        Gtk.main_quit()

    def _poll_recording_state(self):
        if self.recorder_controller.is_stopping:
            return True
        live_active = self.recorder_controller.is_recording
        blink_running = self._blink_timer is not None
        if live_active != self._displayed_recording_state or live_active != blink_running:
            self._update_status_label()
        return True


    def _send_ipc_command(self, command: list) -> bool:
        sock_path = f"/tmp/camwall_{self.monitor_id}.sock"
        if not os.path.exists(sock_path):
            log(f"Overlay: Kein IPC-Socket gefunden unter {sock_path}")
            return False
            
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.connect(sock_path)
            msg = json.dumps({"command": command}) + "\n"
            client.sendall(msg.encode('utf-8'))
            client.close()
            return True
        except Exception as e:
            log(f"Overlay: IPC Fehler bei Befehl {command}: {e}")
            return False

    def on_audio_toggled(self, button):
        is_unmuted = button.get_active()
        success = self._send_ipc_command(["set_property", "mute", not is_unmuted])
        
        if success:
            icon_name = "audio-volume-high" if is_unmuted else "audio-volume-muted"
            tooltip = "Ton ausschalten" if is_unmuted else "Ton einschalten"
            button.set_image(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON))
            button.set_tooltip_text(tooltip)
        else:
            log("Overlay: IPC Befehl fehlgeschlagen, mpv reagiert nicht.")

    def on_shot_clicked(self, button=None):
        self._update_status_label("📸 Klick...")
        threading.Thread(target=self._perform_instant_screenshot, daemon=True).start()

    def _perform_instant_screenshot(self):
        config = load_config()
        try:
            mconf, sconf = get_monitor_and_stream(config, self.monitor_id)
        except Exception as e:
            GLib.idle_add(self._show_error_dialog, str(e))
            return

        stream_name = sconf.get("name", self.monitor_id)
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_title = _safe_title_for_filename(stream_name)
        
        out_dir = Path.home() / ".local" / "share" / "camwall" / "screenshots"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{ts}_{safe_title}.png"
        
        success = self._send_ipc_command(["screenshot-to-file", str(out_path), "video"])
        if not success:
            GLib.idle_add(self._show_error_dialog, "Sofort-Kamera fehlgeschlagen. Ist der Stream aktiv?")
            GLib.idle_add(self._update_status_label, "Fehler")
            return
            
        file_written = False
        for _ in range(30):
            if out_path.exists() and out_path.stat().st_size > 10000:
                time.sleep(0.3)
                file_written = True
                break
            time.sleep(0.2)
            
        if not file_written:
            GLib.idle_add(self._show_error_dialog, "mpv hat keine Bilddatei erstellt.")
            GLib.idle_add(self._update_status_label, "Fehler")
            return

        GLib.idle_add(self._update_status_label, "Stemple Infos...")

        loc = sconf.get("location", "").strip()
        tz_str = sconf.get("timezone", "").strip()
        
        time_str = ""
        if tz_str:
            try:
                from zoneinfo import ZoneInfo
                local_time = datetime.now(ZoneInfo(tz_str))
                time_str = local_time.strftime("%d.%m.%Y - %H:%M Uhr")
            except Exception:
                pass

        weather_str = ""
        if loc:
            try:
                safe_loc = urllib.parse.quote(loc)
                url = f"https://wttr.in/{safe_loc}?format=%c+%t&lang=de"
                req = urllib.request.Request(url, headers={'User-Agent': 'curl/7.68.0'})
                with urllib.request.urlopen(req, timeout=3) as response:
                    weather_str = response.read().decode('utf-8').strip()
            except Exception:
                pass

        if HAS_CAIRO and (loc or tz_str):
            try:
                surface = cairo.ImageSurface.create_from_png(str(out_path))
                ctx = cairo.Context(surface)
                
                ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
                ctx.set_font_size(24)
                
                lines = [stream_name]
                if loc: lines.append(f"Ort: {loc}")
                if time_str: lines.append(f"Zeit: {time_str}")
                if weather_str: lines.append(f"Wetter: {weather_str}")
                
                max_w = 0
                total_h = 0
                for line in lines:
                    ext = ctx.text_extents(line)
                    max_w = max(max_w, ext.width)
                    total_h += 30
                    
                pad = 15
                box_w = max_w + (pad * 2)
                box_h = total_h + (pad * 2) - 10
                
                x = surface.get_width() - box_w - 30
                y = surface.get_height() - box_h - 30
                
                ctx.set_source_rgba(0, 0, 0, 0.65)
                ctx.rectangle(x, y, box_w, box_h)
                ctx.fill()
                
                ctx.set_source_rgba(1, 1, 1, 1)
                curr_y = y + pad + 20
                for line in lines:
                    ctx.move_to(x + pad, curr_y)
                    ctx.show_text(line)
                    curr_y += 30
                    
                surface.write_to_png(str(out_path))
            except Exception as e:
                log(f"Fehler beim Aufdrucken des Info-Stempels: {e}")

        GLib.idle_add(self._update_status_label, "Screenshot fertig")
        
        # HIER IST DER NEUE TOAST-DIALOG: modal=False blockiert nichts mehr!
        GLib.idle_add(self._show_toast_dialog, f"Sofort-Screenshot erstellt:\n{out_path.name}")

    def _show_toast_dialog(self, text: str):
        dlg = Gtk.MessageDialog(
            transient_for=self, 
            modal=False, 
            message_type=Gtk.MessageType.INFO, 
            buttons=Gtk.ButtonsType.NONE, 
            text=text
        )
        dlg.show_all()
        # Zerstört den Dialog verlässlich nach 2500 Millisekunden
        def close_dlg():
            dlg.destroy()
            return False
        GLib.timeout_add(2500, close_dlg)

    def _show_error_dialog(self, text: str):
        dlg = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK, text=text)
        dlg.run()
        dlg.destroy()


    def on_info_toggled(self, button):
        if button.get_active():
            self.info_label.set_markup("<i>Lade lokale Daten...</i>")
            self.info_revealer.set_reveal_child(True)
            threading.Thread(target=self._fetch_weather_and_time, daemon=True).start()
        else:
            self.info_revealer.set_reveal_child(False)
            GLib.timeout_add(350, self._shrink_and_reposition)

    def _shrink_and_reposition(self):
        self.resize(1, 1)
        GLib.timeout_add(50, self._position_and_set_opacity)
        return False

    def _fetch_weather_and_time(self):
        config = load_config()
        try:
            _, sconf = get_monitor_and_stream(config, self.monitor_id)
        except Exception:
            GLib.idle_add(self._update_info_panel, "<i>Stream-Config nicht gefunden.</i>")
            return

        loc = sconf.get("location", "").strip()
        tz_str = sconf.get("timezone", "").strip()
        stream_name = sconf.get("name", "Stream")

        time_str = ""
        if tz_str:
            try:
                from zoneinfo import ZoneInfo
                local_time = datetime.now(ZoneInfo(tz_str))
                time_str = local_time.strftime("%H:%M Uhr")
            except Exception:
                time_str = "Ungültige Zeitzone"

        weather_str = ""
        if loc:
            try:
                safe_loc = urllib.parse.quote(loc)
                url = f"https://wttr.in/{safe_loc}?format=%c+%t+(%C)&lang=de"
                req = urllib.request.Request(url, headers={'User-Agent': 'curl/7.68.0'})
                with urllib.request.urlopen(req, timeout=5) as response:
                    weather_str = response.read().decode('utf-8').strip()
            except Exception:
                weather_str = "Nicht erreichbar"

        info_markup = f"<span weight='bold' size='large' color='#3b82f6'>{stream_name}</span>\n\n"
        has_info = False
        if loc:
            info_markup += f"📍 {loc}\n"
            has_info = True
        if tz_str:
            info_markup += f"🕒 {time_str}\n"
            has_info = True
        if weather_str:
            info_markup += f"🌡️ {weather_str}"

        if not has_info:
            info_markup += "<span size='small'><i>Kein Ort/Zeitzone in Config hinterlegt.\nBitte in der GUI eintragen.</i></span>"

        GLib.idle_add(self._update_info_panel, info_markup)

    def _update_info_panel(self, markup: str):
        self.info_label.set_markup(markup)
        GLib.timeout_add(50, self._position_and_set_opacity)


    def _position_and_set_opacity(self):
        try:
            rect = get_monitor_rect_for_id(self.monitor_id)
            if rect is None:
                self.set_position(Gtk.WindowPosition.CENTER)
            else:
                win_w, win_h = self.get_size()
                margin = 20
                pos_x = rect.x + rect.width - win_w - margin
                pos_y = rect.y + rect.height - win_h - margin
                self.move(pos_x, pos_y)

            self.hover_controller.set_initial_opacity()
        except Exception:
            self.set_position(Gtk.WindowPosition.CENTER)
        return False


    def _set_record_btn_opacity(self, opacity: float) -> None:
        self.btn_record.set_opacity(opacity)
        img = self.btn_record.get_image()
        if img is not None:
            img.set_opacity(opacity)
        self.btn_record.queue_draw()

    def _update_status_label(self, extra: str = ""):
        try:
            config = load_config()
            monitors = config.get("monitors", {})
            mconf = monitors.get(self.monitor_id, {})
            monitor_name = mconf.get("name", self.monitor_id)
        except Exception:
            monitor_name = self.monitor_id

        is_rec = self.recorder_controller.is_recording
        self._displayed_recording_state = is_rec

        if self.recorder_controller.is_stopping:
            rec_text = "Stoppe …"
        elif is_rec:
            rec_text = "Aufnahme: an"
        else:
            rec_text = "Bereit."

        txt = f"{monitor_name} – {rec_text}"
        if extra:
            txt += f" ({extra})"
        self.label_status.set_text(txt)

        # HIER IST DER TRICK FÜRS BLINKEN: btn_record bleibt aktiv (wird nicht grau)!
        self.btn_stop.set_sensitive(is_rec and not self.recorder_controller.is_stopping)

        if is_rec:
            if not self._blink_timer:
                self._blink_state = False
                self._set_record_btn_opacity(0.15)
                self._blink_timer = GLib.timeout_add(700, self._on_blink_record)
        else:
            if self._blink_timer:
                GLib.source_remove(self._blink_timer)
                self._blink_timer = None
            self._blink_state = False
            self._set_record_btn_opacity(1.0)

    def _on_blink_record(self):
        if not self.recorder_controller.is_recording:
            self._blink_timer = None
            self._blink_state = False
            self._set_record_btn_opacity(1.0)
            self._update_status_label()
            return False
        self._blink_state = not self._blink_state
        self._set_record_btn_opacity(1.0 if self._blink_state else 0.15)
        return True


    def on_button_press_event(self, widget, event):
        if event.type == Gdk.EventType.BUTTON_PRESS and event.button == 3:
            menu = self.build_context_menu()
            menu.show_all()
            menu.popup_at_pointer(event)
            return True
            
        if event.type == Gdk.EventType._2BUTTON_PRESS and event.button == 1:
            self.on_shot_clicked()
            return True
            
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

        item_quit = Gtk.MenuItem(label="Overlay schließen")
        item_quit.connect("activate", lambda *_: self.destroy())
        menu.append(item_quit)

        return menu

    def switch_monitor(self, new_monitor_id: str):
        self.monitor_id = new_monitor_id
        self.recorder_controller.monitor_id = new_monitor_id
        self.btn_audio.set_active(False)
        self._position_and_set_opacity()
        self._update_status_label("Monitor gewechselt")

    def _lock_overlay(self):
        self.set_decorated(False)

    def _unlock_overlay(self):
        self.set_decorated(True)

    def _set_opacity_profile(self, value: float):
        self.hover_controller.normal_opacity = value
        self.hover_controller.hover_opacity = 0.95
        self.hover_controller.set_initial_opacity()

    def on_record_clicked(self, button):
        if self.recorder_controller.is_stopping or self.recorder_controller.is_recording:
            return
            
        try:
            self.recorder_controller.start_recording()
            self._update_status_label("gestartet")
        except Exception as e:
            log(f"Crash bei Aufnahme: {e}")
            self._update_status_label("Fehler")
            self._show_error_dialog(f"Fehler beim Starten der Aufnahme:\n{e}")

    def on_stop_clicked(self, button):
        if self.recorder_controller.is_stopping:
            return
        if not self.recorder_controller.is_recording:
            self._update_status_label("keine aktiv")
            return

        self.recorder_controller.is_stopping = True
        self._update_status_label()

        def _stop_worker():
            ok = False
            try:
                ok = self.recorder_controller.stop_recording()
            except Exception as e:
                log(f"Fehler beim Stoppen der Aufnahme: {e}")
            GLib.idle_add(self._on_stop_completed, ok)

        threading.Thread(target=_stop_worker, daemon=True).start()

    def _on_stop_completed(self, ok: bool):
        self._update_status_label("gestoppt" if ok else "keine aktiv")
        return False

    def on_refresh_clicked(self, button):
        self.recorder_controller.refresh_background()
        self.btn_audio.set_active(False)
        self._update_status_label("Refresh")


RecorderOverlayWindow = OverlayWindow

def main():
    monitor_id = "right"
    if len(sys.argv) >= 2:
        monitor_id = sys.argv[1]
    win = RecorderOverlayWindow(monitor_id=monitor_id)
    win.show_all()
    Gtk.main()

if __name__ == "__main__":
    main()
