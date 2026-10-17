import gi
import json

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GObject  # noqa: E402

# Drag and Drop Target Definition
TARGET_ENTRY_STREAM = Gtk.TargetEntry.new("GTK_TREE_MODEL_ROW", Gtk.TargetFlags.SAME_WIDGET, 0)


class StreamTab(Gtk.Box):
    """Tab für Stream-Verwaltung mit Drag&Drop und Kategorien."""

    def __init__(self, main_window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=8)
        self.main_window = main_window
        self.main = main_window

        info_stream = Gtk.Label(
            label="Verwalte hier die Streams. Du kannst Einträge per Drag & Drop verschieben.",
            xalign=0,
        )
        info_stream.set_justify(Gtk.Justification.LEFT)
        self.pack_start(info_stream, False, False, 0)

        # Spalten: [0: is_category (bool), 1: id_or_name (str), 2: Name (str), 3: Typ (str), 4: URL (str), 5: Browser (str)]
        self.stream_store = Gtk.TreeStore(bool, str, str, str, str, str)
        self._load_stream_store()

        treeview = Gtk.TreeView(model=self.stream_store)
        self.stream_treeview = treeview
        self.stream_treeview.set_tooltip_text("Liste der Streams und Kategorien.")

        # Drag and Drop Setup
        treeview.enable_model_drag_source(
            Gdk.ModifierType.BUTTON1_MASK, [TARGET_ENTRY_STREAM], Gdk.DragAction.MOVE
        )
        treeview.enable_model_drag_dest([TARGET_ENTRY_STREAM], Gdk.DragAction.MOVE)
        
        treeview.connect("drag-data-get", self.on_drag_data_get)
        treeview.connect("drag-data-received", self.on_drag_data_received)

        # Spalte: Name (mit Icon für Kategorien)
        col_name = Gtk.TreeViewColumn("Name")
        
        renderer_pixbuf = Gtk.CellRendererPixbuf()
        col_name.pack_start(renderer_pixbuf, False)
        col_name.set_cell_data_func(renderer_pixbuf, self.render_icon)
        
        renderer_text = Gtk.CellRendererText()
        col_name.pack_start(renderer_text, True)
        col_name.set_cell_data_func(renderer_text, self.render_name_bold)

        col_type = Gtk.TreeViewColumn("Typ", Gtk.CellRendererText(), text=3)
        col_url = Gtk.TreeViewColumn("URL", Gtk.CellRendererText(), text=4)

        treeview.append_column(col_name)
        treeview.append_column(col_type)
        treeview.append_column(col_url)

        treeview.set_headers_clickable(True)
        treeview.set_headers_visible(True)
        treeview.get_selection().set_mode(Gtk.SelectionMode.SINGLE)
        
        treeview.expand_all()

        treeview.connect("row-activated", self.on_stream_row_activated)
        treeview.connect("button-press-event", self.on_stream_treeview_button_press)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(treeview)
        scroll.set_min_content_height(260)
        self.pack_start(scroll, True, True, 0)

        # Buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.pack_start(btn_box, False, False, 0)

        btn_add = Gtk.Button(label="Hinzufügen")
        btn_add.set_image(Gtk.Image.new_from_icon_name("list-add", Gtk.IconSize.BUTTON))
        btn_add.set_always_show_image(True)
        
        btn_add_cat = Gtk.Button(label="Neue Kategorie")
        btn_add_cat.set_image(Gtk.Image.new_from_icon_name("folder-new", Gtk.IconSize.BUTTON))
        btn_add_cat.set_always_show_image(True)

        btn_edit = Gtk.Button(label="Bearbeiten")
        btn_edit.set_image(Gtk.Image.new_from_icon_name("document-edit", Gtk.IconSize.BUTTON))
        btn_edit.set_always_show_image(True)

        btn_del = Gtk.Button(label="Löschen")
        btn_del.set_image(Gtk.Image.new_from_icon_name("user-trash", Gtk.IconSize.BUTTON))
        btn_del.set_always_show_image(True)

        btn_preview = Gtk.Button(label="Vorschau")
        btn_preview.set_image(Gtk.Image.new_from_icon_name("media-playback-start", Gtk.IconSize.BUTTON))
        btn_preview.set_always_show_image(True)

        btn_add.connect("clicked", self.on_add_stream_clicked)
        btn_add_cat.connect("clicked", self.on_add_category_clicked)
        btn_edit.connect("clicked", self.on_edit_stream_clicked)
        btn_del.connect("clicked", self.on_delete_stream_clicked)
        btn_preview.connect("clicked", self.on_preview_stream_clicked)

        btn_box.pack_start(btn_add, False, False, 0)
        btn_box.pack_start(btn_add_cat, False, False, 0)
        btn_box.pack_start(btn_edit, False, False, 0)
        btn_box.pack_start(btn_del, False, False, 0)
        btn_box.pack_end(btn_preview, False, False, 0)

    # ------------------------------------------------------------------
    # UI Renderers
    # ------------------------------------------------------------------
    def render_icon(self, column, cell, model, treeiter, data):
        is_category = model[treeiter][0]
        if is_category:
            cell.set_property("icon-name", "folder")
        else:
            cell.set_property("icon-name", "video-x-generic")

    def render_name_bold(self, column, cell, model, treeiter, data):
        is_category = model[treeiter][0]
        name = model[treeiter][2]
        if is_category:
            cell.set_property("markup", f"<b>{name}</b>")
        else:
            cell.set_property("markup", name)

    # ------------------------------------------------------------------
    # Drag & Drop Handlers
    # ------------------------------------------------------------------
    def on_drag_data_get(self, treeview, drag_context, selection_data, info, time):
        model, paths = treeview.get_selection().get_selected_rows()
        if not paths: return
        row_data = treeview.get_model().get_string_from_iter(model.get_iter(paths[0]))
        selection_data.set(selection_data.get_target(), 8, row_data.encode('utf-8'))

    def on_drag_data_received(self, treeview, drag_context, x, y, selection_data, info, time):
        GObject.idle_add(self._save_tree_structure)

    def _save_tree_structure(self):
        structure = []
        def walk_tree(treeiter, parent_list):
            while treeiter is not None:
                is_cat = self.stream_store[treeiter][0]
                item_id = self.stream_store[treeiter][1]
                
                if is_cat:
                    cat_dict = {"category": item_id, "children": []}
                    parent_list.append(cat_dict)
                    child_iter = self.stream_store.iter_children(treeiter)
                    if child_iter:
                        walk_tree(child_iter, cat_dict["children"])
                else:
                    parent_list.append({"stream": item_id})
                    
                treeiter = self.stream_store.iter_next(treeiter)

        root_iter = self.stream_store.get_iter_first()
        if root_iter:
            walk_tree(root_iter, structure)

        self.main.config["stream_order"] = structure
        self.main.config_service.save_config()
        return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_selected_item(self):
        sel = self.stream_treeview.get_selection()
        model, treeiter = sel.get_selected()
        if treeiter is None:
            return None, None, None
        is_category = model[treeiter][0]
        item_id = model[treeiter][1]
        return model, treeiter, (is_category, item_id)

    def _get_selected_stream_id(self):
        model, treeiter, item = self._get_selected_item()
        if item and not item[0]:
            return item[1]
        return None

    def _select_item_by_id(self, target_id: str, is_cat: bool) -> None:
        def matcher(model, path, treeiter, data):
            if model[treeiter][0] == is_cat and model[treeiter][1] == target_id:
                self.stream_treeview.set_cursor(path)
                return True
            return False
        self.stream_store.foreach(matcher, None)

    def _load_stream_store(self) -> None:
        self.stream_store.clear()
        order = self.main.config.get("stream_order", [])
        streams_added = set()

        def append_items(items, parent_iter=None):
            for item in items:
                if "category" in item:
                    cat_name = item["category"]
                    new_iter = self.stream_store.append(parent_iter, [True, cat_name, cat_name, "", "", ""])
                    if "children" in item:
                        append_items(item["children"], new_iter)
                elif "stream" in item:
                    sid = item["stream"]
                    conf = self.main.streams.get(sid)
                    if conf:
                        name = conf.get("name", sid)
                        stype = conf.get("type", "direct")
                        url = conf.get("url", "")
                        browser = conf.get("browser", "")
                        self.stream_store.append(parent_iter, [False, sid, name, stype, url, browser])
                        streams_added.add(sid)

        append_items(order)

        for sid, conf in self.main.streams.items():
            if sid not in streams_added:
                name = conf.get("name", sid)
                stype = conf.get("type", "direct")
                url = conf.get("url", "")
                browser = conf.get("browser", "")
                self.stream_store.append(None, [False, sid, name, stype, url, browser])

    def _show_stream_context_menu(self, event, is_cat: bool, item_id: str) -> None:
        menu = Gtk.Menu()
        def add_item(label: str, handler):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", handler, is_cat, item_id)
            menu.append(item)

        if not is_cat:
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
        is_cat = model[treeiter][0]
        item_id = model[treeiter][1]

        self._show_stream_context_menu(event, is_cat, item_id)
        return True

    def on_stream_row_activated(self, treeview, path, column):
        self.on_edit_stream_clicked(treeview)

    def _on_stream_menu_preview(self, menuitem, is_cat: bool, item_id: str) -> None:
        self._select_item_by_id(item_id, is_cat)
        self.on_preview_stream_clicked(menuitem)

    def _on_stream_menu_wallpaper(self, menuitem, is_cat: bool, item_id: str) -> None:
        self._select_item_by_id(item_id, is_cat)
        self.main.on_set_wallpaper_for_stream(item_id)

    def _on_stream_menu_edit(self, menuitem, is_cat: bool, item_id: str) -> None:
        self._select_item_by_id(item_id, is_cat)
        self.on_edit_stream_clicked(menuitem)

    def _on_stream_menu_delete(self, menuitem, is_cat: bool, item_id: str) -> None:
        self._select_item_by_id(item_id, is_cat)
        self.on_delete_stream_clicked(menuitem)

    def on_add_category_clicked(self, button):
        dlg = Gtk.MessageDialog(transient_for=self.main, modal=True, buttons=Gtk.ButtonsType.OK_CANCEL, text="Name der neuen Kategorie:")
        entry = Gtk.Entry()
        dlg.get_content_area().pack_start(entry, True, True, 0)
        dlg.show_all()
        
        if dlg.run() == Gtk.ResponseType.OK:
            cat_name = entry.get_text().strip()
            if cat_name:
                self.stream_store.append(None, [True, cat_name, cat_name, "", "", ""])
                self._save_tree_structure()
        dlg.destroy()

    def on_add_stream_clicked(self, button):
        dlg = self.main.StreamEditDialog(self.main)
        resp = dlg.run()
        if resp == Gtk.ResponseType.OK:
            values = dlg.get_values()
            try:
                # NEU: location und timezone werden an den Controller übergeben
                sid, conf = self.main.stream_controller.add_stream(
                    values["name"], values["url"], values["type"], values["browser"],
                    values.get("location", ""), values.get("timezone", "")
                )
            except ValueError as e:
                self.main._show_error_dialog(str(e))
                dlg.destroy()
                return

            self.stream_store.append(None, [
                False,
                sid,
                conf.get("name", sid),
                conf.get("type", "direct"),
                conf.get("url", ""),
                conf.get("browser", ""),
            ])
            self._save_tree_structure()
            self.main.log(f"Stream hinzugefügt: {sid} -> {conf}")
            self.main._set_status(f"Stream „{conf.get('name', sid)}“ hinzugefügt.")
            self.main._refresh_monitor_combos()
            self.main._refresh_rec_stream_combo()

        dlg.destroy()

    def on_edit_stream_clicked(self, button):
        model, treeiter, item = self._get_selected_item()
        if not item:
            self.main._show_info_dialog("Bitte wähle zuerst einen Eintrag aus der Liste aus.")
            return

        is_cat, item_id = item
        
        if is_cat:
            dlg = Gtk.MessageDialog(transient_for=self.main, modal=True, buttons=Gtk.ButtonsType.OK_CANCEL, text="Kategorie umbenennen:")
            entry = Gtk.Entry()
            entry.set_text(item_id)
            dlg.get_content_area().pack_start(entry, True, True, 0)
            dlg.show_all()
            if dlg.run() == Gtk.ResponseType.OK:
                new_name = entry.get_text().strip()
                if new_name:
                    model[treeiter][1] = new_name
                    model[treeiter][2] = new_name
                    self._save_tree_structure()
            dlg.destroy()
            return

        sid = item_id
        sconf = self.main.streams.get(sid, {})
        dlg = self.main.StreamEditDialog(self.main, stream_id=sid, stream_conf=sconf)
        resp = dlg.run()
        if resp == Gtk.ResponseType.OK:
            values = dlg.get_values()
            try:
                # NEU: location und timezone werden beim Bearbeiten übergeben
                conf = self.main.stream_controller.edit_stream(
                    sid, values["name"], values["url"], values["type"], values["browser"],
                    values.get("location", ""), values.get("timezone", "")
                )
            except ValueError as e:
                self.main._show_error_dialog(str(e))
                dlg.destroy()
                return

            model[treeiter][2] = conf.get("name", sid)
            model[treeiter][3] = conf.get("type", "")
            model[treeiter][4] = conf.get("url", "")
            model[treeiter][5] = conf.get("browser", "")

            self._save_tree_structure()
            self.main.log(f"Stream bearbeitet: {sid} -> {conf}")
            self.main._set_status(f"Stream „{conf.get('name', sid)}“ bearbeitet.")
            self.main._refresh_monitor_combos()
            self.main._refresh_rec_stream_combo()

        dlg.destroy()

    def on_delete_stream_clicked(self, button):
        model, treeiter, item = self._get_selected_item()
        if not item:
            self.main._show_info_dialog("Bitte wähle einen Eintrag aus.")
            return

        is_cat, item_id = item

        if is_cat:
            msg = Gtk.MessageDialog(transient_for=self.main, modal=True, message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.OK_CANCEL, text=f"Kategorie „{item_id}“ wirklich löschen?")
            msg.format_secondary_text("Streams in dieser Kategorie werden ebenfalls aus der Liste entfernt (aber nicht aus der Config gelöscht, sie erscheinen beim nächsten Start unkategorisiert).")
            resp = msg.run()
            msg.destroy()
            if resp == Gtk.ResponseType.OK:
                model.remove(treeiter)
                self._save_tree_structure()
            return

        sid = item_id
        sconf = self.main.streams.get(sid, {})
        name = sconf.get("name", sid)
        msg = Gtk.MessageDialog(
            transient_for=self.main,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text=f"Stream „{name}“ wirklich löschen?",
        )
        msg.format_secondary_text("Monitore, die diesen Stream nutzen, werden danach auf „kein Stream“ gesetzt.")
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

        model.remove(treeiter)
        self._save_tree_structure()

        self.main._refresh_monitor_combos()
        self.main._refresh_rec_stream_combo()
        self.main._set_status(f"Stream „{name}“ gelöscht.")

    def on_preview_stream_clicked(self, button):
        sid = self._get_selected_stream_id()
        if not sid:
            self.main._show_info_dialog("Bitte zuerst einen Stream auswählen (Kategorien können nicht abgespielt werden).")
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
            self.main._show_error_dialog(f"Vorschau fehlgeschlagen.\nyt-dlp konnte die Stream-URL nicht ermitteln.\n\nFehler:\n{e}")
        except FileNotFoundError as e:
            self.main._show_error_dialog(str(e))
