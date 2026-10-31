#!/usr/bin/env python3
import fcntl
import sys
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from modules.paths import LOG_PATH, PID_DIR
from modules.config_loader import load_config
from modules.monitor_info import get_xrandr_geometries
from modules.stream_resolver import resolve_stream
from modules.wallpaper_engine import kill_existing, start_wallpaper


def log(msg: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


def _touch_grace_file(monitor_id: str) -> None:
    """
    Signalisiert dem Watchdog, dass dieser Monitor gerade (neu) gestartet wird,
    damit der Gesundheitscheck während der yt-dlp-Auflösung und mpv-Startphase
    keinen konkurrierenden Neustart auslöst.
    """
    try:
        Path(f"/tmp/camwall_grace_{monitor_id}").touch(exist_ok=True)
    except Exception:
        pass


@contextmanager
def _monitor_apply_lock(monitor_id: str):
    """
    Verhindert, dass zwei parallele camwall-apply-Prozesse gleichzeitig denselben
    Monitor neu starten, sich gegenseitig die PID-Datei überschreiben und dadurch
    einen alten Stream-Prozess verwaist im Hintergrund weiterlaufen lassen.
    """
    PID_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = PID_DIR / f"apply_{monitor_id}.lock"
    with lock_path.open("w") as lock_fh:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)


def _parse_targets(argv: list[str], monitors_cfg: dict) -> list[str]:
    # akzeptiert left/right (und ignoriert Müll)
    allowed = set(monitors_cfg.keys()) if monitors_cfg else {"left", "right"}
    targets = [a.strip() for a in argv if a.strip() in allowed]
    return targets


def main():
    log("=== camwall-apply gestartet ===")

    config = load_config()
    monitor_geometries = get_xrandr_geometries()
    monitors_cfg = config.get("monitors", {})

    targets = _parse_targets(sys.argv[1:], monitors_cfg)
    if not targets:
        targets = ["left", "right"]

    log(f"Targets: {targets}")

    for monitor_id in targets:
        with _monitor_apply_lock(monitor_id):
            _touch_grace_file(monitor_id)

            # Konfiguration innerhalb des Locks frisch laden, falls dieser Prozess
            # auf einen vorherigen camwall-apply-Lauf gewartet hat.
            config = load_config()
            streams = config.get("streams", {})
            monitors_cfg = config.get("monitors", {})

            # Vorhandenen Stream dieses Monitors sauber beenden
            kill_existing(log, [monitor_id])

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

            # Sicherheitsnetz: Nochmals sicherstellen, dass während der URL-Auflösung
            # kein Prozess auf diesem Monitor übrig geblieben ist, und Anlaufzeit erneuern.
            kill_existing(log, [monitor_id])
            _touch_grace_file(monitor_id)
            start_wallpaper(monitor_id, geometry, url, log)

    log("=== camwall-apply beendet ===")


if __name__ == "__main__":
    main()
