import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402


class MonitorTab(Gtk.Box):
    """Tab für Monitor-Konfiguration."""

    def __init__(self, main_window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=8)
        self.main_window = main_window

        info = Gtk.Label(
            label=(
                "Wähle für jeden Monitor den gewünschten Stream.\n"
                "„(kein Stream)“ lässt den normalen Hintergrund aktiv.\n"
                "Optional kann das Overlay-Icon automatisch starten."
            ),
            xalign=0,
        )
        info.set_justify(Gtk.Justification.LEFT)
        self.pack_start(info, False, False, 0)

        self._build_monitor_rows()

    def _build_monitor_rows(self) -> None:
        main = self.main_window
        monitor_items = list(main.monitors.items())
        if hasattr(main, "log"):
            main.log(
                f"monitors_from_config -> {[(k, v.get('name'), v.get('stream_id')) for k, v in monitor_items]}"
            )

        for mon_id, mconf in monitor_items:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            self.pack_start(row, False, False, 0)

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
            main._fill_monitor_combo(combo, stream_id)
            row.pack_start(combo, True, True, 0)

            chk_overlay = Gtk.CheckButton(label="Overlay automatisch starten")
            chk_overlay.set_active(overlay_autostart)
            row.pack_start(chk_overlay, False, False, 0)

            main.monitor_combo_widgets[mon_id] = combo
            main.monitor_overlay_check_widgets[mon_id] = chk_overlay
