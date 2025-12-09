import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402


class StreamTab(Gtk.Box):
    """Tab für Stream-Verwaltung."""

    def __init__(self, main_window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=8)
        self.main_window = main_window

        info_stream = Gtk.Label(
            label="Verwalte hier die verfügbaren Streams.",
            xalign=0,
        )
        info_stream.set_justify(Gtk.Justification.LEFT)
        self.pack_start(info_stream, False, False, 0)

        self.main = main_window

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
        treeview.connect("button-press-event", self.on_stream_treeview_button_press)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(treeview)
        scroll.set_min_content_height(260)
        self.pack_start(scroll, True, True, 0)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.pack_start(btn_box, False, False, 0)

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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_selected_stream_iter(self):
        sel = self.stream_treeview.get_selection()
        model, treeiter = sel.get_selected()
        return model, treeiter

    def _get_selected_stream_id(self):
        model, treeiter = self._get_selected_stream_iter()
        if treeiter is None:
            return None
        return model[treeiter][0]

    def _select_stream_by_id(self, sid: str) -> None:
        def matcher(model, path, treeiter, target_sid):
            if model[treeiter][0] == target_sid:
                self.stream_treeview.set_cursor(path)
                return True
            return False

        self.stream_store.foreach(matcher, sid)

    def _load_stream_store(self) -> None:
        self.stream_store.clear()
        for sid, conf in self.main.stream_controller.get_sorted_streams():
            name = conf.get("name", sid)
            stype = conf.get("type", "direct")
            url = conf.get("url", "")
            browser = conf.get("browser", "")
            self.stream_store.append([sid, name, stype, url, browser])

    def _show_stream_context_menu(self, event, sid: str) -> None:
        menu = Gtk.Menu()

        def add_item(label: str, handler):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", handler, sid)
            menu.append(item)

        add_item("Vorschau", self._on_stream_menu_preview)
        add_item("Als Hintergrund setzen", self._on_stream_menu_wallpaper)
        add_item("Bearbeiten", self._on_stream_menu_edit)
        add_item("Löschen", self._on_stream_menu_delete)

        menu.show_all()
        menu.popup_at_pointer(event)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def on_stream_treeview_button_press(self, treeview, event):
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
        sid = model[treeiter][0]

        self._show_stream_context_menu(event, sid)
        return True

    def on_stream_row_activated(self, treeview, path, column):
        self.on_edit_stream_clicked(treeview)

    def _on_stream_menu_preview(self, menuitem, sid: str) -> None:
        self._select_stream_by_id(sid)
        self.on_preview_stream_clicked(menuitem)

    def _on_stream_menu_wallpaper(self, menuitem, sid: str) -> None:
        self._select_stream_by_id(sid)
        self.main.on_set_wallpaper_for_stream(sid)

    def _on_stream_menu_edit(self, menuitem, sid: str) -> None:
        self._select_stream_by_id(sid)
        self.on_edit_stream_clicked(menuitem)

    def _on_stream_menu_delete(self, menuitem, sid: str) -> None:
        self._select_stream_by_id(sid)
        self.on_delete_stream_clicked(menuitem)

    def on_add_stream_clicked(self, button):
        dlg = self.main.StreamEditDialog(self.main)
        resp = dlg.run()
        if resp == Gtk.ResponseType.OK:
            values = dlg.get_values()
            try:
                sid, conf = self.main.stream_controller.add_stream(
                    values["name"], values["url"], values["type"], values["browser"]
                )
            except ValueError as e:
                self.main._show_error_dialog(str(e))
                dlg.destroy()
                return

            self.stream_store.append([
                sid,
                conf.get("name", sid),
                conf.get("type", "direct"),
                conf.get("url", ""),
                conf.get("browser", ""),
            ])
            self.main.log(f"Stream hinzugefügt: {sid} -> {conf}")
            self.main._set_status(f"Stream „{conf.get('name', sid)}“ hinzugefügt.")
            self.main._refresh_monitor_combos()
            self.main._refresh_rec_stream_combo()

        dlg.destroy()

    def on_edit_stream_clicked(self, button):
        sid = self._get_selected_stream_id()
        if not sid:
            self.main._show_info_dialog("Bitte wähle zuerst einen Stream aus der Liste aus.")
            return

        sconf = self.main.streams.get(sid, {})
        dlg = self.main.StreamEditDialog(self.main, stream_id=sid, stream_conf=sconf)
        resp = dlg.run()
        if resp == Gtk.ResponseType.OK:
            values = dlg.get_values()
            try:
                conf = self.main.stream_controller.edit_stream(
                    sid, values["name"], values["url"], values["type"], values["browser"]
                )
            except ValueError as e:
                self.main._show_error_dialog(str(e))
                dlg.destroy()
                return

            model, treeiter = self._get_selected_stream_iter()
            if treeiter is not None:
                model[treeiter][1] = conf.get("name", sid)
                model[treeiter][2] = conf.get("type", "")
                model[treeiter][3] = conf.get("url", "")
                model[treeiter][4] = conf.get("browser", "")

            self.main.log(f"Stream bearbeitet: {sid} -> {conf}")
            self.main._set_status(f"Stream „{conf.get('name', sid)}“ bearbeitet.")
            self.main._refresh_monitor_combos()
            self.main._refresh_rec_stream_combo()

        dlg.destroy()

    def on_delete_stream_clicked(self, button):
        sid = self._get_selected_stream_id()
        if not sid:
            self.main._show_info_dialog("Bitte wähle einen Stream aus.")
            return

        sconf = self.main.streams.get(sid, {})
        name = sconf.get("name", sid)
        msg = Gtk.MessageDialog(
            transient_for=self.main,
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

        self.main.log(f"Stream löschen angefordert: {sid}")

        try:
            self.main.monitor_controller.clear_stream_from_monitors(sid)
            self.main.stream_controller.delete_stream(sid)
        except ValueError as e:
            self.main._show_error_dialog(str(e))
            return

        model, treeiter = self._get_selected_stream_iter()
        if treeiter is not None:
            model.remove(treeiter)

        self.main._refresh_monitor_combos()
        self.main._refresh_rec_stream_combo()
        self.main._set_status(f"Stream „{name}“ gelöscht.")

    def on_preview_stream_clicked(self, button):
        sid = self._get_selected_stream_id()
        if not sid:
            self.main._show_info_dialog("Bitte zuerst einen Stream auswählen.")
            return

        try:
            sconf = self.main.streams.get(sid)
            if not sconf:
                raise ValueError("Konfiguration für diesen Stream fehlt.")
            self.main.stream_controller.preview_stream(sid)
            self.main._set_status(f"Vorschau für „{sconf.get('name', sid)}“ gestartet.")
        except ValueError as e:
            self.main._show_error_dialog(str(e))
        except RuntimeError as e:
            self.main._show_error_dialog(
                "Vorschau fehlgeschlagen.\n"
                "yt-dlp konnte die Stream-URL nicht ermitteln.\n\n"
                f"Fehler:\n{e}"
            )
        except FileNotFoundError as e:
            self.main._show_error_dialog(str(e))
