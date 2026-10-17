# -*- coding: utf-8 -*-
import json
import uuid
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

# Hier speichern wir unseren Sendeplan ab
SCHEDULE_FILE = Path.home() / ".local" / "share" / "camwall" / "schedule.json"

def load_schedules():
    if not SCHEDULE_FILE.exists():
        return []
    try:
        with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_schedules(data):
    try:
        with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception:
        pass

class ScheduleEditDialog(Gtk.Dialog):
    def __init__(self, parent, schedule_item=None, streams=None):
        super().__init__(title="Zeitplan bearbeiten", transient_for=parent, flags=Gtk.DialogFlags.MODAL)
        self.set_default_size(400, 250)
        self.set_border_width(10)
        self.streams = streams or {}
        
        box = self.get_content_area()
        grid = Gtk.Grid(column_spacing=10, row_spacing=10, margin=10)
        box.add(grid)
        
        # Uhrzeit
        grid.attach(Gtk.Label(label="Uhrzeit (HH:MM):", xalign=0), 0, 0, 1, 1)
        self.entry_time = Gtk.Entry(text="18:00")
        self.entry_time.set_placeholder_text("z.B. 18:00")
        grid.attach(self.entry_time, 1, 0, 1, 1)
        
        # Monitor
        grid.attach(Gtk.Label(label="Monitor:", xalign=0), 0, 1, 1, 1)
        self.combo_monitor = Gtk.ComboBoxText()
        self.combo_monitor.append("left", "Linker Monitor")
        self.combo_monitor.append("right", "Rechter Monitor")
        self.combo_monitor.set_active_id("left")
        grid.attach(self.combo_monitor, 1, 1, 1, 1)
        
        # Stream
        grid.attach(Gtk.Label(label="Stream:", xalign=0), 0, 2, 1, 1)
        self.combo_stream = Gtk.ComboBoxText()
        self.combo_stream.append("none", "(Ausschalten / Kein Stream)")
        
        # Streams alphabetisch sortieren
        sorted_streams = sorted(self.streams.items(), key=lambda x: x[1].get("name", x[0]).lower())
        for sid, sconf in sorted_streams:
            self.combo_stream.append(sid, sconf.get("name", sid))
        self.combo_stream.set_active_id("none")
        grid.attach(self.combo_stream, 1, 2, 1, 1)
        
        # Aktiv-Schalter
        self.check_active = Gtk.CheckButton(label="Aktiv")
        self.check_active.set_active(True)
        grid.attach(self.check_active, 1, 3, 1, 1)
        
        self.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        self.add_button("Speichern", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)
        
        # Falls wir bearbeiten, füllen wir die Felder mit den bestehenden Daten
        if schedule_item:
            self.entry_time.set_text(schedule_item.get("time", "18:00"))
            self.combo_monitor.set_active_id(schedule_item.get("monitor", "left"))
            stream_id = schedule_item.get("stream_id", "none")
            if stream_id in self.streams or stream_id == "none":
                self.combo_stream.set_active_id(stream_id)
            self.check_active.set_active(schedule_item.get("active", True))
            
        self.show_all()
        
    def get_values(self):
        return {
            "time": self.entry_time.get_text().strip(),
            "monitor": self.combo_monitor.get_active_id(),
            "stream_id": self.combo_stream.get_active_id(),
            "active": self.check_active.get_active()
        }

class ScheduleTab(Gtk.Box):
    def __init__(self, main_window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.set_border_width(10)
        self.main_window = main_window
        
        # Info Label
        info = Gtk.Label(label="Hier kannst du einstellen, wann Streams automatisch wechseln sollen.\n(Format: 08:30, 18:00 usw.)")
        info.set_xalign(0)
        self.pack_start(info, False, False, 0)
        
        # Die Tabelle (ListStore) für die Übersicht
        self.liststore = Gtk.ListStore(str, str, str, str, bool, str)
        self.treeview = Gtk.TreeView(model=self.liststore)
        
        for i, title in enumerate(["ID", "Uhrzeit", "Monitor", "Stream"]):
            if i == 0: continue # ID verstecken
            renderer = Gtk.CellRendererText()
            col = Gtk.TreeViewColumn(title, renderer, text=i)
            self.treeview.append_column(col)
            
        renderer_toggle = Gtk.CellRendererToggle()
        renderer_toggle.connect("toggled", self.on_active_toggled)
        col_active = Gtk.TreeViewColumn("Aktiv", renderer_toggle, active=4)
        self.treeview.append_column(col_active)
        
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.treeview)
        self.pack_start(scroll, True, True, 0)
        
        # Die Aktions-Buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.pack_start(btn_box, False, False, 0)
        
        btn_add = Gtk.Button(label="Neu")
        btn_edit = Gtk.Button(label="Bearbeiten")
        btn_del = Gtk.Button(label="Löschen")
        
        btn_add.connect("clicked", self.on_add_clicked)
        btn_edit.connect("clicked", self.on_edit_clicked)
        btn_del.connect("clicked", self.on_del_clicked)
        
        btn_box.pack_start(btn_add, False, False, 0)
        btn_box.pack_start(btn_edit, False, False, 0)
        btn_box.pack_start(btn_del, False, False, 0)
        
        self.refresh_list()
        
    def refresh_list(self):
        self.liststore.clear()
        schedules = load_schedules()
        # Einträge chronologisch sortieren
        schedules.sort(key=lambda x: x.get("time", "00:00"))
        streams = getattr(self.main_window, "streams", {})
        
        for s in schedules:
            stream_name = "(Aus)" if s.get("stream_id") == "none" else streams.get(s.get("stream_id"), {}).get("name", s.get("stream_id"))
            mon_name = "Links" if s.get("monitor") == "left" else "Rechts"
            self.liststore.append([
                s.get("id", ""),
                s.get("time", ""),
                mon_name,
                stream_name,
                s.get("active", True),
                s.get("stream_id", "")
            ])
            
    def on_active_toggled(self, widget, path):
        self.liststore[path][4] = not self.liststore[path][4]
        self.save_from_liststore()
        
    def save_from_liststore(self):
        data = []
        for row in self.liststore:
            mon = "left" if row[2] == "Links" else "right"
            data.append({
                "id": row[0],
                "time": row[1],
                "monitor": mon,
                "stream_id": row[5],
                "active": row[4]
            })
        save_schedules(data)
        
    def on_add_clicked(self, widget):
        dlg = ScheduleEditDialog(self.main_window, streams=self.main_window.streams)
        response = dlg.run()
        if response == Gtk.ResponseType.OK:
            vals = dlg.get_values()
            vals["id"] = str(uuid.uuid4())
            schedules = load_schedules()
            schedules.append(vals)
            save_schedules(schedules)
            self.refresh_list()
        dlg.destroy()
        
    def on_edit_clicked(self, widget):
        selection = self.treeview.get_selection()
        model, treeiter = selection.get_selected()
        if treeiter:
            row_id = model[treeiter][0]
            schedules = load_schedules()
            item = next((x for x in schedules if x.get("id") == row_id), None)
            if item:
                dlg = ScheduleEditDialog(self.main_window, schedule_item=item, streams=self.main_window.streams)
                response = dlg.run()
                if response == Gtk.ResponseType.OK:
                    vals = dlg.get_values()
                    item.update(vals)
                    save_schedules(schedules)
                    self.refresh_list()
                dlg.destroy()
                
    def on_del_clicked(self, widget):
        selection = self.treeview.get_selection()
        model, treeiter = selection.get_selected()
        if treeiter:
            row_id = model[treeiter][0]
            schedules = load_schedules()
            schedules = [x for x in schedules if x.get("id") != row_id]
            save_schedules(schedules)
            self.refresh_list()
