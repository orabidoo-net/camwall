import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk


class MonitorTab(Gtk.Box):
    def __init__(self, main_window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.main = main_window

        info = Gtk.Label(
            label="Wähle pro Monitor einen Stream und optional Overlay-Autostart. "
                  "Mit „Refresh“ werden die Hintergründe neu gestartet.",
            xalign=0,
        )
        self.pack_start(info, False, False, 0)

        # Header row
        header = Gtk.Grid(column_spacing=12, row_spacing=6)
        header.attach(Gtk.Label(label="<b>Monitor</b>", use_markup=True, xalign=0), 0, 0, 1, 1)
        header.attach(Gtk.Label(label="<b>Stream</b>", use_markup=True, xalign=0), 1, 0, 1, 1)
        header.attach(Gtk.Label(label="<b>Overlay</b>", use_markup=True, xalign=0), 2, 0, 1, 1)
        header.attach(Gtk.Label(label="<b>Aktionen</b>", use_markup=True, xalign=0), 3, 0, 1, 1)
        self.pack_start(header, False, False, 0)

        frame = Gtk.Frame()
        self.pack_start(frame, True, True, 0)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        outer.set_border_width(10)
        frame.add(outer)

        monitors = self.main.monitors or {}
        if not monitors:
            outer.pack_start(
                Gtk.Label(label="Keine Monitore in der Konfiguration gefunden.", xalign=0),
                False, False, 0
            )
            self.show_all()
            return

        grid = Gtk.Grid(column_spacing=12, row_spacing=10)
        outer.pack_start(grid, False, False, 0)

        row = 0
        for mon_id, mconf in monitors.items():
            name = mconf.get("name", mon_id)
            geom = mconf.get("geometry", "")
            stream_id = mconf.get("stream_id", "none") or "none"
            overlay_autostart = bool(mconf.get("overlay_autostart", False))

            mon_label = Gtk.Label(label=f"{name}\n<small>{geom}</small>", use_markup=True, xalign=0)
            grid.attach(mon_label, 0, row, 1, 1)

            combo = Gtk.ComboBoxText()
            self.main._fill_monitor_combo(combo, stream_id)
            grid.attach(combo, 1, row, 1, 1)

            chk = Gtk.CheckButton(label="Autostart")
            chk.set_active(overlay_autostart)
            grid.attach(chk, 2, row, 1, 1)

            btn_refresh = Gtk.Button(label="Refresh")
            btn_refresh.set_tooltip_text("Startet nur diesen Monitor neu (Hintergrund/Stream neu starten).")
            btn_refresh.connect("clicked", lambda _b, mid=mon_id: self.main.refresh_wallpapers(monitor_id=mid))
            grid.attach(btn_refresh, 3, row, 1, 1)

            # Referenzen zurück ins MainWindow, damit Apply lesen kann
            self.main.monitor_combo_widgets[mon_id] = combo
            self.main.monitor_overlay_check_widgets[mon_id] = chk

            row += 1

        # Refresh all
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        outer.pack_start(actions, False, False, 0)
        actions.pack_start(Gtk.Label(), True, True, 0)

        btn_refresh_all = Gtk.Button(label="Refresh (alle)")
        btn_refresh_all.set_tooltip_text("Startet alle Monitore neu.")
        btn_refresh_all.connect("clicked", lambda _b: self.main.refresh_wallpapers())
        actions.pack_start(btn_refresh_all, False, False, 0)

        self.show_all()
