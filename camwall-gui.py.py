#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import subprocess
from pathlib import Path
from datetime import datetime

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio, GLib, Gdk  # noqa: E402

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


# Datenverzeichnisse für Aufnahmen
DATA_DIR = Path.home() / ".local" / "share" / "camwall"
RECORDINGS_DIR = DATA_DIR / "recordings"


# ---------------------------------------------------------------------------
# Konfiguration laden / speichern
# ---------------------------------------------------------------------------

try:
    from modules.config_loader import load_config, save_config
except Exception as e:
    print("Fehler beim Import von modules.config_loader:", e, file=sys.stderr)
    sys.exit(1)

# Cleanup optional importieren (für .mp4.part Aufräumfunktion)
try:
    from modules.cleanup import cleanup_recordings
except Exception as e:
    def cleanup_recordings():
        log(f"Warnung: cleanup_recordings konnte nicht importiert werden.")
        return [], 0


# ---------------------------------------------------------------------------
# Hilfsfunktionen Streams
# ---------------------------------------------------------------------------


def make_stream_id_from_name(name: str) -> str:
    """Erzeuge aus einem Anzeigenamen eine einfache ID (z. B. 'Santa Village' -> 'santa_village')."""
    base = (
        name.strip()
        .lower()
        .replace(" ", "_")
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789_"
    base = "".join(ch for ch in base if ch in allowed) or "stream"
    return base


def human_readable_size(num_bytes: int) -> str:
    """Dateigröße hübsch formatieren."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"
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

        # Konfiguration laden
        self.config = load_config()
        self.streams = self.config.get("streams", {})
        self.monitors = self.config.get("monitors", {})

        log("=== GUI-Start ===")
        log(f"config['monitors'] = {self.monitors}")
        log(f"streams keys = {list(self.streams.keys())}")

        # Dictionaries für Widgets
        self.monitor_combo_widgets = {}
        self.monitor_overlay_check_widgets = {}

        # Grundlayout
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(outer)

        header = Gtk.Label(
            label="<b>Camwall – Live-Stream Hintergründe</b>", use_markup=True
        )
        header.set_xalign(0)
        outer.pack_start(header, False, False, 0)

        sub = Gtk.Label(
            label="Verwalte Bildschirm-Hintergründe, Streams und Aufnahmen.",
            xalign=0,
        )
        outer.pack_start(sub, False, False, 0)

        # Notebook (Tabs)
        notebook = Gtk.Notebook()
        outer.pack_start(notebook, True, True, 0)

        tab1 = self._build_tab_monitors()
        notebook.append_page(tab1, Gtk.Label(label="Bildschirm-Hintergründe"))

        tab2 = self._build_tab_streams()
        notebook.append_page(tab2, Gtk.Label(label="Stream-Verwaltung"))

        tab3 = self._build_tab_recorder()
        notebook.append_page(tab3, Gtk.Label(label="Aufnahme & Screenshots"))

        # Statuszeile
        self.status_label = Gtk.Label(xalign=0)
        self.status_label.set_margin_top(4)
        self._set_status("Bereit.")
        outer.pack_start(self.status_label, False, False, 0)

        # Untere Buttons
        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        outer.pack_start(action_box, False, False, 0)

        action_box.pack_start(Gtk.Label(), True, True, 0)

        btn_cancel = Gtk.Button(label="Abbrechen")
        btn_cancel_icon = Gtk.Image.new_from_icon_name("window-close", Gtk.IconSize.BUTTON)
        btn_cancel.set_image(btn_cancel_icon)
        btn_cancel.set_always_show_image(True)
        btn_cancel.set_tooltip_text("Änderungen verwerfen und Fenster schließen.")

        btn_apply = Gtk.Button(label="Anwenden")
        btn_apply_icon = Gtk.Image.new_from_icon_name("emblem-ok", Gtk.IconSize.BUTTON)
        btn_apply.set_image(btn_apply_icon)
        btn_apply.set_always_show_image(True)
        btn_apply.set_tooltip_text(
            "Änderungen speichern und Live-Hintergründe aktualisieren."
        )

        btn_cancel.connect("clicked", self.on_cancel_clicked)
        btn_apply.connect("clicked", self.on_apply_clicked)

        action_box.pack_start(btn_cancel, False, False, 0)
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

    # ------------------------------------------------------------------
    # TAB 1 – Bildschirm-Hintergründe
    # ------------------------------------------------------------------

    def _build_tab_monitors(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=8)

        info = Gtk.Label(
            label=(
                "Wähle für jeden Monitor den gewünschten Stream.\n"
                "„(kein Stream)“ lässt den normalen Hintergrund aktiv.\n"
                "Optional kann das Overlay-Icon automatisch starten."
            ),
            xalign=0,
        )
        info.set_justify(Gtk.Justification.LEFT)
        box.pack_start(info, False, False, 0)

        self._build_monitor_rows(box)
        return box

    # ------------------------------------------------------------------
    # Monitore
    # ------------------------------------------------------------------

    def _build_monitor_rows(self, container: Gtk.Box) -> None:
        monitor_items = list(self.monitors.items())
        log(
            f"monitors_from_config -> {[(k, v.get('name'), v.get('stream_id')) for k, v in monitor_items]}"
        )

        for mon_id, mconf in monitor_items:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            container.pack_start(row, False, False, 0)

            name = mconf.get("name", mon_id)
            stream_id = mconf.get("stream_id", "none")
            overlay_autostart = bool(mconf.get("overlay_autostart", False))

            lbl = Gtk.Label(label=name + ":", xalign=0)
            lbl.set_size_request(140, -1)
            row.pack_start(lbl, False, False, 0)

            combo = Gtk.ComboBoxText()
            combo.set_hexpand(True)
            combo.set_tooltip_text(
                f"Stream für Monitor „{name}“ auswählen."
            )
            self._fill_monitor_combo(combo, stream_id)
            row.pack_start(combo, True, True, 0)

            chk_overlay = Gtk.CheckButton(label="Overlay automatisch starten")
            chk_overlay.set_active(overlay_autostart)
            row.pack_start(chk_overlay, False, False, 0)

            self.monitor_combo_widgets[mon_id] = combo
            self.monitor_overlay_check_widgets[mon_id] = chk_overlay

    def _fill_monitor_combo(self, combo: Gtk.ComboBoxText, current_id: str) -> None:
        if not current_id:
            current_id = "none"

        model = combo.get_model()
        if model is not None:
            while len(model) > 0:
                combo.remove(0)

        combo.append("none", "(kein Stream)")

        id_name_pairs = [
            (sid, sconf.get("name", sid)) for sid, sconf in self.streams.items()
        ]
        id_name_pairs.sort(key=lambda x: x[1].lower())

        for sid, name in id_name_pairs:
            combo.append(sid, name)

        effective_id = (
            current_id
            if current_id in self.streams or current_id == "none"
            else "none"
        )
        combo.set_active_id(effective_id)
        log(f"_fill_monitor_combo: requested={current_id}, effective={effective_id}")

    def _refresh_monitor_combos(self) -> None:
        for mon_id, combo in self.monitor_combo_widgets.items():
            prev_id = combo.get_active_id() or "none"
            self._fill_monitor_combo(combo, prev_id)

    # ------------------------------------------------------------------
    # TAB 2 – Stream-Verwaltung
    # ------------------------------------------------------------------

    def _build_tab_streams(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=8)

        info_stream = Gtk.Label(
            label="Verwalte hier die verfügbaren Streams.",
            xalign=0,
        )
        info_stream.set_justify(Gtk.Justification.LEFT)
        box.pack_start(info_stream, False, False, 0)

        # ListStore der Streams
        self.stream_store = Gtk.ListStore(str, str, str, str, str)
        self._load_stream_store()

        treeview = Gtk.TreeView(model=self.stream_store)
        self.stream_treeview = treeview
        self.stream_treeview.set_tooltip_text("Liste der konfigurierten Streams.")

        col_name = Gtk.TreeViewColumn("Name", Gtk.CellRendererText(), text=1)
        col_type = Gtk.TreeViewColumn("Typ", Gtk.CellRendererText(), text=2)
        col_url = Gtk.TreeViewColumn("URL", Gtk.CellRendererText(), text=3)

        treeview.append_column(col_name)
        treeview.append_column(col_type)
        treeview.append_column(col_url)

        treeview.set_headers_clickable(True)
        treeview.set_headers_visible(True)
        treeview.get_selection().set_mode(Gtk.SelectionMode.SINGLE)

        treeview.connect("row-activated", self.on_stream_row_activated)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(treeview)
        scroll.set_min_content_height(260)
        box.pack_start(scroll, True, True, 0)

        # Buttons unter der Liste
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.pack_start(btn_box, False, False, 0)

        btn_add = Gtk.Button(label="Hinzufügen")
        btn_add_icon = Gtk.Image.new_from_icon_name("list-add", Gtk.IconSize.BUTTON)
        btn_add.set_image(btn_add_icon)
        btn_add.set_always_show_image(True)

        btn_edit = Gtk.Button(label="Bearbeiten")
        btn_edit_icon = Gtk.Image.new_from_icon_name("document-edit", Gtk.IconSize.BUTTON)
        btn_edit.set_image(btn_edit_icon)
        btn_edit.set_always_show_image(True)

        btn_del = Gtk.Button(label="Löschen")
        btn_del_icon = Gtk.Image.new_from_icon_name("user-trash", Gtk.IconSize.BUTTON)
        btn_del.set_image(btn_del_icon)
        btn_del.set_always_show_image(True)

        btn_preview = Gtk.Button(label="Vorschau")
        btn_preview_icon = Gtk.Image.new_from_icon_name(
            "media-playback-start", Gtk.IconSize.BUTTON
        )
        btn_preview.set_image(btn_preview_icon)
        btn_preview.set_always_show_image(True)

        btn_add.connect("clicked", self.on_add_stream_clicked)
        btn_edit.connect("clicked", self.on_edit_stream_clicked)
        btn_del.connect("clicked", self.on_delete_stream_clicked)
        btn_preview.connect("clicked", self.on_preview_stream_clicked)

        btn_box.pack_start(btn_add, False, False, 0)
        btn_box.pack_start(btn_edit, False, False, 0)
        btn_box.pack_start(btn_del, False, False, 0)
        btn_box.pack_end(btn_preview, False, False, 0)

        return box
    # ------------------------------------------------------------------
    # Streams – ListStore laden
    # ------------------------------------------------------------------

    def _load_stream_store(self) -> None:
        self.stream_store.clear()
        for sid, conf in self.streams.items():
            name = conf.get("name", sid)
            stype = conf.get("type", "direct")
            url = conf.get("url", "")
            browser = conf.get("browser", "")
            self.stream_store.append([sid, name, stype, url, browser])

    def _get_selected_stream_iter(self):
        sel = self.stream_treeview.get_selection()
        model, treeiter = sel.get_selected()
        return model, treeiter

    def _get_selected_stream_id(self):
        model, treeiter = self._get_selected_stream_iter()
        if treeiter is None:
            return None
        return model[treeiter][0]

    # ------------------------------------------------------------------
    # Streams: Events
    # ------------------------------------------------------------------

    def on_stream_row_activated(self, treeview, path, column):
        self.on_edit_stream_clicked(treeview)

    # ------------------------------------------------------------------
    # Buttons: Stream Hinzufügen / Bearbeiten / Löschen / Vorschau
    # ------------------------------------------------------------------

    def on_add_stream_clicked(self, button):
        dlg = StreamEditDialog(self)
        resp = dlg.run()
        if resp == Gtk.ResponseType.OK:
            values = dlg.get_values()
            name = values["name"]
            url = values["url"]
            stype = values["type"]
            browser = values["browser"]

            if not name or not url:
                self._show_error_dialog("Name und URL dürfen nicht leer sein.")
                dlg.destroy()
                return

            if stype == "youtube_cookies" and not browser:
                self._show_error_dialog(
                    "Für YouTube mit Cookies muss ein Browser angegeben werden (z. B. firefox)."
                )
                dlg.destroy()
                return

            base_id = make_stream_id_from_name(name)
            sid = base_id
            i = 2
            while sid in self.streams:
                sid = f"{base_id}_{i}"
                i += 1

            self.streams[sid] = {
                "name": name,
                "url": url,
                "type": stype,
                "browser": browser,
            }
            self.stream_store.append([sid, name, stype, url, browser])
            log(f"Stream hinzugefügt: {sid} -> {self.streams[sid]}")

            self._set_status(f"Stream „{name}“ hinzugefügt.")
            self._refresh_monitor_combos()
            self._refresh_rec_stream_combo()

        dlg.destroy()

    def on_edit_stream_clicked(self, button):
        sid = self._get_selected_stream_id()
        if not sid:
            self._show_info_dialog("Bitte wähle zuerst einen Stream aus der Liste aus.")
            return

        sconf = self.streams.get(sid, {})
        dlg = StreamEditDialog(self, stream_id=sid, stream_conf=sconf)
        resp = dlg.run()
        if resp == Gtk.ResponseType.OK:
            values = dlg.get_values()
            name = values["name"]
            url = values["url"]
            stype = values["type"]
            browser = values["browser"]

            if not name or not url:
                self._show_error_dialog("Name und URL dürfen nicht leer sein.")
                dlg.destroy()
                return

            if stype == "youtube_cookies" and not browser:
                self._show_error_dialog(
                    "Für YouTube mit Cookies muss ein Browser angegeben werden (z. B. firefox)."
                )
                dlg.destroy()
                return

            self.streams[sid] = {
                "name": name,
                "url": url,
                "type": stype,
                "browser": browser,
            }

            model, treeiter = self._get_selected_stream_iter()
            if treeiter is not None:
                model[treeiter][1] = name
                model[treeiter][2] = stype
                model[treeiter][3] = url
                model[treeiter][4] = browser

            log(f"Stream bearbeitet: {sid} -> {self.streams[sid]}")
            self._set_status(f"Stream „{name}“ bearbeitet.")
            self._refresh_monitor_combos()
            self._refresh_rec_stream_combo()

        dlg.destroy()

    def on_delete_stream_clicked(self, button):
        sid = self._get_selected_stream_id()
        if not sid:
            self._show_info_dialog("Bitte wähle einen Stream aus.")
            return

        sconf = self.streams.get(sid, {})
        name = sconf.get("name", sid)
        msg = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text=f"Stream „{name}“ wirklich löschen?",
        )
        msg.format_secondary_text(
            "Monitore, die diesen Stream nutzen, werden danach auf „kein Stream“ gesetzt."
        )
        resp = msg.run()
        msg.destroy()

        if resp != Gtk.ResponseType.OK:
            return

        log(f"Stream löschen angefordert: {sid}")

        # Monitore zurücksetzen
        for mon_id, mconf in self.monitors.items():
            if mconf.get("stream_id") == sid:
                mconf["stream_id"] = "none"

        # Stream löschen
        if sid in self.streams:
            del self.streams[sid]

        model, treeiter = self._get_selected_stream_iter()
        if treeiter is not None:
            model.remove(treeiter)

        self._refresh_monitor_combos()
        self._refresh_rec_stream_combo()
        self._set_status(f"Stream „{name}“ gelöscht.")

    # ------------------------------------------------------------------
    # Stream-Vorschau
    # ------------------------------------------------------------------

    def on_preview_stream_clicked(self, button):
        sid = self._get_selected_stream_id()
        if not sid:
            self._show_info_dialog("Bitte zuerst einen Stream auswählen.")
            return

        sconf = self.streams.get(sid)
        if not sconf:
            self._show_error_dialog("Konfiguration für diesen Stream fehlt.")
            return

        stype = sconf.get("type", "direct")
        url = (sconf.get("url") or "").strip()
        if not url:
            self._show_error_dialog("Für diesen Stream ist keine URL hinterlegt.")
            return

        final_url = url

        try:
            if stype == "youtube_cookies":
                browser = sconf.get("browser", "firefox")
                log(f"Preview: yt-dlp (mit Cookies, Browser={browser}) für {url}")
                result = subprocess.run(
                    ["yt-dlp", "-g", "--cookies-from-browser", browser, url],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0 or not result.stdout.strip():
                    self._show_error_dialog(
                        "Vorschau fehlgeschlagen.\n"
                        "yt-dlp konnte die Stream-URL nicht ermitteln.\n\n"
                        f"Fehler:\n{(result.stderr or '').strip() or 'unbekannt'}"
                    )
                    return
                final_url = result.stdout.strip().splitlines()[-1]

            elif stype == "youtube":
                log(f"Preview: yt-dlp (ohne Cookies) für {url}")
                result = subprocess.run(
                    ["yt-dlp", "-g", url],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0 or not result.stdout.strip():
                    self._show_error_dialog(
                        "Vorschau fehlgeschlagen.\n"
                        "yt-dlp konnte die Stream-URL nicht ermitteln.\n\n"
                        f"Fehler:\n{(result.stderr or '').strip() or 'unbekannt'}"
                    )
                    return
                final_url = result.stdout.strip().splitlines()[-1]

            else:
                log(f"Preview: direkter Stream für {url}")

        except FileNotFoundError:
            self._show_error_dialog(
                "yt-dlp ist nicht installiert.\n"
                "Bitte installiere das Paket 'yt-dlp', um YouTube-Streams testen zu können."
            )
            return

        try:
            log(f"Preview: starte mpv mit URL={final_url}")
            title_arg = f"--title=Vorschau: {sconf.get('name', sid)}"
            subprocess.Popen(
                ["mpv", "--force-window=yes", title_arg, final_url]
            )
            self._set_status(f"Vorschau für „{sconf.get('name', sid)}“ gestartet.")
        except FileNotFoundError:
            self._show_error_dialog(
                "mpv wurde nicht gefunden.\n"
                "Bitte installiere 'mpv', um die Vorschau nutzen zu können."
            )
            return
    # ------------------------------------------------------------------
    # TAB 3 – Aufnahme & Screenshots
    # ------------------------------------------------------------------

    def _build_tab_recorder(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=8)

        info = Gtk.Label(
            label=(
                "Hier kannst du Aufnahmen starten/stoppen und Screenshots erstellen.\n"
                "Die Aufnahmen liegen unter ~/.local/share/camwall/recordings."
            ),
            xalign=0,
        )
        info.set_justify(Gtk.Justification.LEFT)
        box.pack_start(info, False, False, 0)

        # --- Aufnahme-Steuerung ---
        control_frame = Gtk.Frame(label="Aufnahme-Steuerung")
        control_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=6)
        control_frame.add(control_box)
        box.pack_start(control_frame, False, False, 0)

        grid = Gtk.Grid(column_spacing=8, row_spacing=8, margin=4)
        control_box.pack_start(grid, False, False, 0)

        # Streamwahl
        lbl_stream = Gtk.Label(label="Stream:", xalign=0)
        self.rec_stream_combo = Gtk.ComboBoxText()
        self.rec_stream_combo.set_hexpand(True)
        grid.attach(lbl_stream, 0, 0, 1, 1)
        grid.attach(self.rec_stream_combo, 1, 0, 1, 1)

        # Titel
        lbl_title = Gtk.Label(label="Aufnahme-Titel:", xalign=0)
        self.rec_title_entry = Gtk.Entry()
        self.rec_title_entry.set_placeholder_text("z. B. 'Hush Bar Abendaufnahme'")
        grid.attach(lbl_title, 0, 1, 1, 1)
        grid.attach(self.rec_title_entry, 1, 1, 1, 1)

        # Buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        control_box.pack_start(btn_box, False, False, 0)

        btn_rec_start = Gtk.Button(label="Aufnahme starten")
        btn_rec_start.set_image(Gtk.Image.new_from_icon_name("media-record", Gtk.IconSize.BUTTON))
        btn_rec_start.set_always_show_image(True)

        btn_rec_stop = Gtk.Button(label="Aufnahme stoppen")
        btn_rec_stop.set_image(Gtk.Image.new_from_icon_name("media-playback-stop", Gtk.IconSize.BUTTON))
        btn_rec_stop.set_always_show_image(True)

        btn_shot = Gtk.Button(label="Screenshot")
        btn_shot.set_image(Gtk.Image.new_from_icon_name("camera-photo", Gtk.IconSize.BUTTON))
        btn_shot.set_always_show_image(True)

        btn_rec_start.connect("clicked", self.on_rec_start_clicked)
        btn_rec_stop.connect("clicked", self.on_rec_stop_clicked)
        btn_shot.connect("clicked", self.on_rec_screenshot_clicked)

        btn_box.pack_start(btn_rec_start, False, False, 0)
        btn_box.pack_start(btn_rec_stop, False, False, 0)
        btn_box.pack_start(btn_shot, False, False, 0)

        # --- Aufnahmen-Browser ---
        browser_frame = Gtk.Frame(label="Aufnahmen-Browser")
        browser_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=6)
        browser_frame.add(browser_box)
        box.pack_start(browser_frame, True, True, 0)

        self.media_store = Gtk.ListStore(str, str, str, str)
        self.media_treeview = Gtk.TreeView(model=self.media_store)

        col_name = Gtk.TreeViewColumn("Datei", Gtk.CellRendererText(), text=1)
        col_mtime = Gtk.TreeViewColumn("Geändert am", Gtk.CellRendererText(), text=2)
        col_size = Gtk.TreeViewColumn("Größe", Gtk.CellRendererText(), text=3)

        self.media_treeview.append_column(col_name)
        self.media_treeview.append_column(col_mtime)
        self.media_treeview.append_column(col_size)

        self.media_treeview.get_selection().set_mode(Gtk.SelectionMode.SINGLE)

        media_scroll = Gtk.ScrolledWindow()
        media_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        media_scroll.set_min_content_height(220)
        media_scroll.add(self.media_treeview)

        browser_box.pack_start(media_scroll, True, True, 0)

        # NEU: Statistik-Label
        self.media_stats_label = Gtk.Label(xalign=0)
        self.media_stats_label.set_margin_top(2)
        browser_box.pack_start(self.media_stats_label, False, False, 0)

        # Buttons
        media_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        browser_box.pack_start(media_btn_box, False, False, 0)

        btn_open = Gtk.Button(label="Abspielen")
        btn_open.set_image(Gtk.Image.new_from_icon_name("media-playback-start", Gtk.IconSize.BUTTON))
        btn_open.set_always_show_image(True)

        btn_open_folder = Gtk.Button(label="Im Dateimanager öffnen")
        btn_open_folder.set_image(Gtk.Image.new_from_icon_name("folder-open", Gtk.IconSize.BUTTON))
        btn_open_folder.set_always_show_image(True)

        btn_delete = Gtk.Button(label="Löschen")
        btn_delete.set_image(Gtk.Image.new_from_icon_name("user-trash", Gtk.IconSize.BUTTON))
        btn_delete.set_always_show_image(True)

        # NEU: Cleanup-Button
        btn_cleanup = Gtk.Button(label="Aufräumen")
        btn_cleanup.set_image(Gtk.Image.new_from_icon_name("edit-clear", Gtk.IconSize.BUTTON))
        btn_cleanup.set_always_show_image(True)
        btn_cleanup.set_tooltip_text("Temporäre .mp4.part-Dateien entfernen.")

        btn_refresh = Gtk.Button(label="Liste aktualisieren")
        btn_refresh.set_image(Gtk.Image.new_from_icon_name("view-refresh", Gtk.IconSize.BUTTON))
        btn_refresh.set_always_show_image(True)

        btn_open.connect("clicked", self.on_media_play_clicked)
        btn_open_folder.connect("clicked", self.on_media_open_folder_clicked)
        btn_delete.connect("clicked", self.on_media_delete_clicked)
        btn_cleanup.connect("clicked", self.on_media_cleanup_clicked)
        btn_refresh.connect("clicked", self.on_media_refresh_clicked)

        media_btn_box.pack_start(btn_open, False, False, 0)
        media_btn_box.pack_start(btn_open_folder, False, False, 0)
        media_btn_box.pack_start(btn_delete, False, False, 0)
        media_btn_box.pack_start(btn_cleanup, False, False, 0)
        media_btn_box.pack_end(btn_refresh, False, False, 0)

        # Streamliste + Aufnahmenliste füllen
        self._refresh_rec_stream_combo()
        self._load_media_list()

        return box

    # ------------------------------------------------------------------
    # Recorder-Helfer
    # ------------------------------------------------------------------

    def _refresh_rec_stream_combo(self) -> None:
        combo = self.rec_stream_combo
        model = combo.get_model()
        prev_id = combo.get_active_id() if combo.get_active() >= 0 else None

        if model is not None:
            while len(model) > 0:
                combo.remove(0)

        combo.append("", "Bitte Stream wählen …")

        id_name_pairs = [
            (sid, sconf.get("name", sid)) for sid, sconf in self.streams.items()
        ]
        id_name_pairs.sort(key=lambda x: x[1].lower())

        for sid, name in id_name_pairs:
            combo.append(sid, name)

        if prev_id and prev_id in self.streams:
            combo.set_active_id(prev_id)
        else:
            combo.set_active(0)
    def _get_recorder_stream_conf(self):
        sid = self.rec_stream_combo.get_active_id()
        if not sid:
            return None, None
        sconf = self.streams.get(sid)
        return sid, sconf

    # ------------------------------------------------------------------
    # Aufnahme starten / stoppen / Screenshot
    # ------------------------------------------------------------------

    def on_rec_start_clicked(self, button):
        sid, sconf = self._get_recorder_stream_conf()
        if not sid or not sconf:
            self._show_info_dialog("Bitte zuerst einen Stream auswählen.")
            return

        url = (sconf.get("url") or "").strip()
        if not url:
            self._show_error_dialog("Für diesen Stream ist keine URL hinterlegt.")
            return

        stype = sconf.get("type", "direct")
        browser = sconf.get("browser", "").strip()

        title = self.rec_title_entry.get_text().strip()
        if not title:
            title = sconf.get("name", sid)

        cmd = ["python3", "-m", "modules.stream_recorder", "record", url, title]
        if stype == "youtube_cookies":
            if not browser:
                self._show_error_dialog(
                    "Dieser Stream ist als YouTube (mit Cookies) konfiguriert,\n"
                    "aber es wurde kein Browser angegeben."
                )
                return
            cmd.append(browser)

        log(f"Recorder start: cmd={cmd}")
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._set_status(f"Aufnahme für „{sconf.get('name', sid)}“ gestartet.")
        except FileNotFoundError:
            self._show_error_dialog(
                "Konnte modules.stream_recorder nicht starten.\n"
                "Stimmt der Installationspfad?"
            )

    def on_rec_stop_clicked(self, button):
        cmd = ["python3", "-m", "modules.stream_recorder", "stop"]
        log(f"Recorder stop: cmd={cmd}")
        try:
            result = subprocess.run(cmd, check=False, capture_output=True, text=True)
            stdout = (result.stdout or "").strip()
            if stdout:
                log(f"Recorder stop stdout: {stdout}")
            self._set_status("Aufnahme gestoppt (oder es lief keine).")
            self._load_media_list()
        except FileNotFoundError:
            self._show_error_dialog("Konnte modules.stream_recorder nicht starten.")

    def on_rec_screenshot_clicked(self, button):
        sid, sconf = self._get_recorder_stream_conf()
        if not sid or not sconf:
            self._show_info_dialog("Bitte zuerst einen Stream auswählen.")
            return

        url = (sconf.get("url") or "").strip()
        if not url:
            self._show_error_dialog("Für diesen Stream ist keine URL hinterlegt.")
            return

        stype = sconf.get("type", "direct")
        browser = sconf.get("browser", "").strip()

        title = self.rec_title_entry.get_text().strip()
        if not title:
            title = sconf.get("name", sid)

        cmd = ["python3", "-m", "modules.stream_recorder", "shot", url, title]
        if stype == "youtube_cookies":
            if not browser:
                self._show_error_dialog(
                    "Dieser Stream ist als YouTube (mit Cookies) konfiguriert,\n"
                    "aber es wurde kein Browser angegeben."
                )
                return
            cmd.append(browser)

        log(f"Recorder screenshot: cmd={cmd}")
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._set_status(
                f"Screenshot für „{sconf.get('name', sid)}“ wird erstellt …"
            )
        except FileNotFoundError:
            self._show_error_dialog("Konnte modules.stream_recorder nicht starten.")

    # ------------------------------------------------------------------
    # Aufnahmen-Browser Funktionen
    # ------------------------------------------------------------------

    def _load_media_list(self):
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        self.media_store.clear()

        files = sorted(
            RECORDINGS_DIR.glob("*.mp4"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        total_bytes = 0
        for p in files:
            try:
                st = p.stat()
            except FileNotFoundError:
                continue
            total_bytes += st.st_size
            size_str = human_readable_size(st.st_size)
            mtime_str = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
            self.media_store.append([str(p), p.name, mtime_str, size_str])

        if hasattr(self, "media_stats_label") and self.media_stats_label is not None:
            total_str = human_readable_size(total_bytes)
            self.media_stats_label.set_text(
                f"Gesamt: {len(files)} Datei(en), {total_str}."
            )

        self._set_status(f"Aufnahmenliste aktualisiert ({len(files)} Einträge).")

    def _get_selected_media_path(self) -> Path | None:
        sel = self.media_treeview.get_selection()
        model, treeiter = sel.get_selected()
        if treeiter is None:
            return None
        return Path(model[treeiter][0])

    def on_media_refresh_clicked(self, button):
        self._load_media_list()

    def on_media_play_clicked(self, button):
        path = self._get_selected_media_path()
        if not path or not path.exists():
            self._show_info_dialog("Bitte zuerst eine Aufnahme auswählen.")
            return

        try:
            subprocess.Popen(["mpv", str(path)])
            self._set_status(f"Abspielen von „{path.name}“ gestartet.")
        except FileNotFoundError:
            self._show_error_dialog(
                "mpv wurde nicht gefunden.\n"
                "Bitte installiere 'mpv', um Aufnahmen direkt abzuspielen."
            )

    def on_media_open_folder_clicked(self, button):
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.Popen(["xdg-open", str(RECORDINGS_DIR)])
            self._set_status("Aufnahmenordner geöffnet.")
        except FileNotFoundError:
            self._show_error_dialog("xdg-open nicht gefunden.")

    def on_media_delete_clicked(self, button):
        path = self._get_selected_media_path()
        if not path or not path.exists():
            self._show_info_dialog("Bitte zuerst eine Aufnahme auswählen.")
            return

        msg = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text=f"Aufnahme „{path.name}“ wirklich löschen?",
        )
        resp = msg.run()
        msg.destroy()

        if resp != Gtk.ResponseType.OK:
            return

        try:
            path.unlink()
            self._set_status(f"Aufnahme „{path.name}“ gelöscht.")
            self._load_media_list()
        except Exception as e:
            self._show_error_dialog(f"Fehler beim Löschen:\n{e}")

    def on_media_cleanup_clicked(self, button):
        removed, freed = cleanup_recordings()

        if not removed and freed == 0:
            self._show_info_dialog(
                "Es wurden keine temporären Aufnahmedateien (*.mp4.part) gefunden."
            )
            return

        freed_str = human_readable_size(freed)
        msg = (
            "Aufräumen abgeschlossen.\n\n"
            f"Freigegebener Speicher: {freed_str}\n"
            f"Entfernte Dateien: {len(removed)}"
        )

        self._show_info_dialog(msg)
        self._set_status(f"Cleanup durchgeführt – freigegeben: {freed_str}")
        self._load_media_list()

    # ------------------------------------------------------------------
    # Anwenden / Abbrechen
    # ------------------------------------------------------------------

    def on_cancel_clicked(self, button):
        self._set_status("Abgebrochen. Änderungen wurden nicht übernommen.")
        self.destroy()

    def on_apply_clicked(self, button):
        log("Anwenden geklickt")

        # Monitore speichern
        for mon_id, combo in self.monitor_combo_widgets.items():
            active_id = combo.get_active_id()
            sid = active_id if active_id and active_id != "none" else "none"

            overlay_flag = False
            chk = self.monitor_overlay_check_widgets.get(mon_id)
            if chk is not None:
                overlay_flag = bool(chk.get_active())

            if mon_id not in self.monitors:
                self.monitors[mon_id] = {
                    "name": mon_id,
                    "geometry": "",
                    "stream_id": sid,
                    "overlay_autostart": overlay_flag,
                }
            else:
                self.monitors[mon_id]["stream_id"] = sid
                self.monitors[mon_id]["overlay_autostart"] = overlay_flag

        self.config["monitors"] = self.monitors
        self.config["streams"] = self.streams

        save_config(self.config)
        log("Konfiguration gespeichert, starte camwall-apply.py")

        try:
            subprocess.Popen(
                ["/usr/bin/env", "python3", "/opt/camwall/camwall-apply.py"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._set_status("Hintergründe werden aktualisiert …")
        except Exception as e:
            log(f"Fehler beim Start von camwall-apply.py: {e}")
            self._show_error_dialog(
                "Konfiguration gespeichert,\n"
                "aber camwall-apply.py konnte nicht gestartet werden.\n\n"
                f"Fehler: {e}"
            )

        # Overlay-Autostart
        for mon_id, mconf in self.monitors.items():
            if mconf.get("overlay_autostart"):
                try:
                    subprocess.Popen(
                        ["camwall-overlay", mon_id],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    log(f"Overlay-Autostart für Monitor {mon_id} ausgelöst.")
                except Exception as e:
                    log(f"Fehler beim Start von camwall-overlay ({mon_id}): {e}")

        self.destroy()

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
    win = CamwallMainWindow()
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
