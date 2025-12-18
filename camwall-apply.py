#!/usr/bin/env python3
import sys
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from modules.paths import LOG_PATH
from modules.config_loader import load_config
from modules.monitor_info import get_xrandr_geometries
from modules.stream_resolver import resolve_stream
from modules.wallpaper_engine import kill_existing, start_wallpaper


def log(msg: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


def _parse_targets(argv: list[str], monitors_cfg: dict) -> list[str]:
    # akzeptiert left/right (und ignoriert Müll)
    allowed = set(monitors_cfg.keys()) if monitors_cfg else {"left", "right"}
    targets = [a.strip() for a in argv if a.strip() in allowed]
    return targets


def main():
    log("=== camwall-apply gestartet ===")

    config = load_config()
    monitor_geometries = get_xrandr_geometries()

    streams = config.get("streams", {})
    monitors_cfg = config.get("monitors", {})

    targets = _parse_targets(sys.argv[1:], monitors_cfg)
    if not targets:
        targets = ["left", "right"]

    log(f"Targets: {targets}")

    # Wichtig: nur die Ziel-Monitore killen (sonst reloaden beide)
    kill_existing(log, targets)

    for monitor_id in targets:
        mon_conf = monitors_cfg.get(monitor_id, {})
        stream_id = mon_conf.get("stream_id", "none")
        if stream_id == "none":
            log(f"{monitor_id}: kein Stream zugeordnet, überspringe.")
            continue

        stream = streams.get(stream_id)
        if not stream:
            log(f"{monitor_id}: Stream '{stream_id}' nicht gefunden.")
            continue

        geometry = monitor_geometries.get(monitor_id)
        if not geometry:
            log(f"{monitor_id}: keine Geometrie gefunden, überspringe.")
            continue

        url = resolve_stream(stream, log)
        if not url:
            log(f"{monitor_id}: konnte URL für Stream '{stream_id}' nicht ermitteln.")
            continue

        start_wallpaper(monitor_id, geometry, url, log)

    log("=== camwall-apply beendet ===")


if __name__ == "__main__":
    main()
