#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime

from modules.config_loader import load_config
from modules.monitor_info import monitors_from_config
from modules.stream_resolver import resolve_stream
from modules.wallpaper_engine import kill_existing, start_wallpaper

LOG_PATH = Path.home() / ".local" / "share" / "camwall" / "camwall.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")

def main():
    log("=== camwall-apply (modular) gestartet ===")

    cfg = load_config()
    if not cfg:
        log("Keine Config geladen, breche ab.")
        return

    # Alte Instanzen beenden
    kill_existing(log=log)

    streams = cfg.get("streams", {})
    monitors = monitors_from_config(cfg)

    for mon in monitors:
        if mon.stream_id == "none":
            log(f"Monitor {mon.id}: kein Stream zugeordnet, überspringe.")
            continue

        stream = streams.get(mon.stream_id)
        if not stream:
            log(f"Monitor {mon.id}: Stream '{mon.stream_id}' nicht in Config gefunden.")
            continue

        url = resolve_stream(stream, log=log)
        if not url:
            log(f"Monitor {mon.id}: konnte URL für Stream '{mon.stream_id}' nicht ermitteln.")
            continue

        if not mon.geometry:
            log(f"Monitor {mon.id}: keine Geometrie gesetzt.")
            continue

        start_wallpaper(mon.geometry, url, log=log)

    log("=== camwall-apply (modular) beendet (Hintergründe laufen im Hintergrund) ===")

if __name__ == "__main__":
    main()
