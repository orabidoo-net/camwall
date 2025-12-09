from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402


class RecorderTab(Gtk.Box):
    """Tab für Aufnahmen und Screenshots."""

    def __init__(self, main_window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=8)
        self.main = main_window

        info = Gtk.Label(
            label=(
                "Hier kannst du Aufnahmen starten/stoppen und Screenshots erstellen.\n"
                "Die Aufnahmen liegen unter ~/.local/share/camwall/recordings."
            ),
            xalign=0,
        )
        info.set_justify(Gtk.Justification.LEFT)
        self.pack_start(info, False, False, 0)

        control_frame = Gtk.Frame(label="Aufnahme-Steuerung")
        control_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=6)
        control_frame.add(control_box)
        self.pack_start(control_frame, False, False, 0)

        grid = Gtk.Grid(column_spacing=8, row_spacing=8, margin=4)
        control_box.pack_start(grid, False, False, 0)

        lbl_stream = Gtk.Label(label="Stream:", xalign=0)
        self.rec_stream_combo = Gtk.ComboBoxText()
        self.rec_stream_combo.set_hexpand(True)
        grid.attach(lbl_stream, 0, 0, 1, 1)
        grid.attach(self.rec_stream_combo, 1, 0, 1, 1)
        self.main.rec_stream_combo = self.rec_stream_combo

        lbl_title = Gtk.Label(label="Aufnahme-Titel:", xalign=0)
        self.rec_title_entry = Gtk.Entry()
        self.rec_title_entry.set_placeholder_text("z. B. 'Hush Bar Abendaufnahme'")
        grid.attach(lbl_title, 0, 1, 1, 1)
        grid.attach(self.rec_title_entry, 1, 1, 1, 1)

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

        browser_frame = Gtk.Frame(label="Aufnahmen-Browser")
        browser_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=6)
        browser_frame.add(browser_box)
        self.pack_start(browser_frame, True, True, 0)

        self.media_store = Gtk.ListStore(str, str, str, str)
        self.media_treeview = Gtk.TreeView(model=self.media_store)

        col_name = Gtk.TreeViewColumn("Datei", Gtk.CellRendererText(), text=1)
        col_mtime = Gtk.TreeViewColumn("Geändert am", Gtk.CellRendererText(), text=2)
        col_size = Gtk.TreeViewColumn("Größe", Gtk.CellRendererText(), text=3)

        self.media_treeview.append_column(col_name)
        self.media_treeview.append_column(col_mtime)
        self.media_treeview.append_column(col_size)

        self.media_treeview.get_selection().set_mode(Gtk.SelectionMode.SINGLE)
        self.media_treeview.connect("row-activated", self.on_media_row_activated)
        self.media_treeview.connect("button-press-event", self.on_media_treeview_button_press)

        media_scroll = Gtk.ScrolledWindow()
        media_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        media_scroll.set_min_content_height(220)
        media_scroll.add(self.media_treeview)

        browser_box.pack_start(media_scroll, True, True, 0)

        self.media_stats_label = Gtk.Label(xalign=0)
        self.media_stats_label.set_margin_top(2)
        browser_box.pack_start(self.media_stats_label, False, False, 0)

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

        self.main._refresh_rec_stream_combo()
        self._load_media_list()

    # ------------------------------------------------------------------
    # Recorder helpers
    # ------------------------------------------------------------------

    def _get_recorder_stream_conf(self):
        sid = self.rec_stream_combo.get_active_id()
        if not sid:
            return None, None
        sconf = self.main.streams.get(sid)
        return sid, sconf

    def _load_media_list(self):
        self.media_store.clear()
        entries, total_bytes = self.main.recorder_controller.load_media_list()
        for path, name, mtime_str, size_str in entries:
            self.media_store.append([path, name, mtime_str, size_str])

        if hasattr(self, "media_stats_label") and self.media_stats_label is not None:
            total_str = self.main.human_readable_size(total_bytes)
            self.media_stats_label.set_text(
                f"Gesamt: {len(entries)} Datei(en), {total_str}."
            )

        self.main._set_status(f"Aufnahmenliste aktualisiert ({len(entries)} Einträge).")

    def _get_selected_media_path(self) -> Path | None:
        sel = self.media_treeview.get_selection()
        model, treeiter = sel.get_selected()
        if treeiter is None:
            return None
        return Path(model[treeiter][0])

    def _select_media_by_path(self, target_path: Path) -> None:
        def matcher(model, path, treeiter, data):
            if Path(model[treeiter][0]) == data:
                self.media_treeview.set_cursor(path)
                return True
            return False

        self.media_store.foreach(matcher, target_path)

    def _show_media_context_menu(self, event, media_path: Path) -> None:
        menu = Gtk.Menu()

        def add_item(label: str, handler):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", handler, media_path)
            menu.append(item)

        add_item("Abspielen", self._on_media_menu_play)
        add_item("Im Ordner öffnen", self._on_media_menu_open_folder)
        add_item("Umbenennen", self._on_media_menu_rename)
        add_item("Löschen", self._on_media_menu_delete)

        menu.show_all()
        menu.popup_at_pointer(event)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def on_rec_start_clicked(self, button):
        sid, sconf = self._get_recorder_stream_conf()
        if not sid or not sconf:
            self.main._show_info_dialog("Bitte zuerst einen Stream auswählen.")
            return

        title = self.rec_title_entry.get_text().strip()
        try:
            self.main.recorder_controller.start_recording(sid, sconf, title)
            self.main._set_status(f"Aufnahme für „{sconf.get('name', sid)}“ gestartet.")
        except ValueError as e:
            self.main._show_error_dialog(str(e))
        except FileNotFoundError:
            self.main._show_error_dialog(
                "Konnte modules.stream_recorder nicht starten.\n"
                "Stimmt der Installationspfad?"
            )

    def on_rec_stop_clicked(self, button):
        try:
            self.main.recorder_controller.stop_recording()
            self.main._set_status("Aufnahme gestoppt (oder es lief keine).")
            self._load_media_list()
        except FileNotFoundError:
            self.main._show_error_dialog("Konnte modules.stream_recorder nicht starten.")

    def on_rec_screenshot_clicked(self, button):
        sid, sconf = self._get_recorder_stream_conf()
        if not sid or not sconf:
            self.main._show_info_dialog("Bitte zuerst einen Stream auswählen.")
            return

        title = self.rec_title_entry.get_text().strip()
        try:
            self.main.recorder_controller.take_screenshot(sid, sconf, title)
            self.main._set_status(
                f"Screenshot für „{sconf.get('name', sid)}“ wird erstellt …"
            )
        except ValueError as e:
            self.main._show_error_dialog(str(e))
        except FileNotFoundError:
            self.main._show_error_dialog("Konnte modules.stream_recorder nicht starten.")

    def on_media_refresh_clicked(self, button):
        self._load_media_list()

    def on_media_row_activated(self, treeview, path, column):
        treeview.get_selection().select_path(path)
        self.on_media_play_clicked(treeview)

    def on_media_treeview_button_press(self, treeview, event):
        if event.button != 3:
            return False

        hit = treeview.get_path_at_pos(int(event.x), int(event.y))
        if not hit:
            return False

        path, column, cell_x, cell_y = hit
        treeview.grab_focus()
        treeview.set_cursor(path, column, False)

        model = treeview.get_model()
        treeiter = model.get_iter(path)
        media_path = Path(model[treeiter][0])

        self._show_media_context_menu(event, media_path)
        return True

    def _on_media_menu_play(self, menuitem, media_path: Path) -> None:
        self._select_media_by_path(media_path)
        self.on_media_play_clicked(menuitem)

    def _on_media_menu_open_folder(self, menuitem, media_path: Path) -> None:
        self._select_media_by_path(media_path)
        self.on_media_open_folder_clicked(menuitem)

    def _on_media_menu_rename(self, menuitem, media_path: Path) -> None:
        self._select_media_by_path(media_path)
        self.on_media_rename_clicked(media_path)

    def _on_media_menu_delete(self, menuitem, media_path: Path) -> None:
        self._select_media_by_path(media_path)
        self.on_media_delete_clicked(menuitem)

    def on_media_play_clicked(self, button):
        path = self._get_selected_media_path()
        if not path or not path.exists():
            self.main._show_info_dialog("Bitte zuerst eine Aufnahme auswählen.")
            return

        try:
            self.main.recorder_controller.open_media_file(path)
            self.main._set_status(f"Abspielen von „{path.name}“ gestartet.")
        except FileNotFoundError:
            self.main._show_error_dialog(
                "mpv wurde nicht gefunden.\n"
                "Bitte installiere 'mpv', um Aufnahmen direkt abzuspielen."
            )

    def on_media_open_folder_clicked(self, button):
        try:
            self.main.recorder_controller.open_media_folder()
            self.main._set_status("Aufnahmenordner geöffnet.")
        except FileNotFoundError:
            self.main._show_error_dialog("xdg-open nicht gefunden.")

    def on_media_delete_clicked(self, button):
        path = self._get_selected_media_path()
        if not path or not path.exists():
            self.main._show_info_dialog("Bitte zuerst eine Aufnahme auswählen.")
            return

        msg = Gtk.MessageDialog(
            transient_for=self.main,
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
            self.main.recorder_controller.delete_media_file(path)
            self.main._set_status(f"Aufnahme „{path.name}“ gelöscht.")
            self._load_media_list()
        except Exception as e:
            self.main._show_error_dialog(f"Fehler beim Löschen:\n{e}")

    def on_media_rename_clicked(self, path: Path):
        dlg = Gtk.Dialog(
            title="Aufnahme umbenennen",
            transient_for=self.main,
            flags=Gtk.DialogFlags.MODAL
        )
        dlg.set_default_size(380, 120)
        box = dlg.get_content_area()

        entry = Gtk.Entry()
        entry.set_text(path.name)
        box.add(entry)

        dlg.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        dlg.add_button("Umbenennen", Gtk.ResponseType.OK)
        dlg.show_all()

        resp = dlg.run()
        if resp == Gtk.ResponseType.OK:
            new_name = entry.get_text().strip()
            if new_name:
                try:
                    new_path = self.main.recorder_controller.rename_media_file(path, new_name)
                    self.main._set_status(f'"{path.name}" wurde umbenannt in "{new_path.name}".')
                except Exception as e:
                    self.main._show_error_dialog(f"Fehler beim Umbenennen:\n{e}")
        dlg.destroy()
        self._load_media_list()

    def on_media_cleanup_clicked(self, button):
        removed, freed = self.main.recorder_controller.cleanup_recordings()

        if not removed and freed == 0:
            self.main._show_info_dialog(
                "Es wurden keine temporären Aufnahmedateien (*.mp4.part) gefunden."
            )
            return

        freed_str = self.main.human_readable_size(freed)
        msg = (
            "Aufräumen abgeschlossen.\n\n"
            f"Freigegebener Speicher: {freed_str}\n"
            f"Entfernte Dateien: {len(removed)}"
        )

        self.main._show_info_dialog(msg)
        self.main._set_status(f"Cleanup durchgeführt – freigegeben: {freed_str}")
        self._load_media_list()
