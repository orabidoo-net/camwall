#!/usr/bin/env python3
import json
import subprocess
import os
from pathlib import Path
from datetime import datetime

CONFIG_PATH = Path.home() / ".config" / "camwall" / "config.json"
LOG_DIR = Path.home() / ".local" / "share" / "camwall"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "camwall.log"

def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")

def load_config():
    if not CONFIG_PATH.exists():
        log(f"Config {CONFIG_PATH} nicht gefunden.")
        return None
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)

def get_stream_url(stream: dict) -> str | None:
    stype = stream.get("type")
    url = stream.get("url")
    if not url:
        log("Stream hat keine URL.")
        return None

    # Typ 1: direkte URL (z.B. fertige .m3u8)
    if stype == "direct":
        log(f"Verwende direkte URL für Stream '{stream.get('name')}': {url}")
        return url

    # Typ 2: YouTube mit Browser-Cookies (wie Santa)
    if stype == "youtube_cookies":
        browser = stream.get("browser", "firefox")
        log(f"Hole Stream-URL via yt-dlp (Browser={browser}) für {url}")
        try:
            # yt-dlp -g gibt i.d.R. eine oder mehrere Zeilen aus -> wir nehmen die letzte
            result = subprocess.run(
                ["yt-dlp", "-g", f"--cookies-from-browser", browser, url],
                check=True,
                capture_output=True,
                text=True
            )
            lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
            if not lines:
                log("yt-dlp hat keine URL geliefert.")
                return None
            final_url = lines[-1]
            log(f"yt-dlp URL: {final_url}")
            return final_url
        except subprocess.CalledProcessError as e:
            log(f"yt-dlp Fehler: {e}\nSTDERR: {e.stderr}")
            return None

    log(f"Unbekannter Stream-Typ: {stype}")
    return None

def start_wallpaper(geometry: str, url: str) -> None:
    # DISPLAY sicherstellen (für Autostart später wichtig)
    env = os.environ.copy()
    env.setdefault("DISPLAY", ":0")

    log(f"Starte xwinwrap/mpv mit Geometrie {geometry}")
    cmd = [
        "xwinwrap",
        "-g", geometry,
        "-ni",
        "-b",
        "-nf",
        "-fdt",
        "--",
        "mpv",
        "--no-audio",
        "--loop",
        "--no-border",
        "-wid", "WID",
        url,
    ]
    subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

def kill_existing():
    # Sehr schlicht: wir nehmen an, dass xwinwrap/mpv nur für Camwall laufen
    for cmd in (
        ["pkill", "-f", "xwinwrap"],
        ["pkill", "-f", "mpv.*manifest.googlevideo.com"],
    ):
        try:
            subprocess.run(cmd, check=False)
        except Exception as e:
            log(f"Fehler beim Killen ({cmd}): {e}")

def main():
    log("=== camwall-apply gestartet ===")
    cfg = load_config()
    if cfg is None:
        log("Keine Config, breche ab.")
        return

    kill_existing()

    monitors = cfg.get("monitors", {})
    streams = cfg.get("streams", {})

    for monitor_id, mconf in monitors.items():
        stream_id = mconf.get("stream_id", "none")
        if stream_id == "none":
            log(f"Monitor {monitor_id}: kein Stream zugeordnet, überspringe.")
            continue

        stream = streams.get(stream_id)
        if not stream:
            log(f"Monitor {monitor_id}: Stream '{stream_id}' nicht in Config gefunden.")
            continue

        url = get_stream_url(stream)
        if not url:
            log(f"Monitor {monitor_id}: konnte URL für Stream '{stream_id}' nicht ermitteln.")
            continue

        geometry = mconf.get("geometry")
        if not geometry:
            log(f"Monitor {monitor_id}: keine Geometrie gesetzt.")
            continue

        start_wallpaper(geometry, url)

    log("=== camwall-apply beendet (Hintergründe laufen im Hintergrund) ===")

if __name__ == "__main__":
    main()
