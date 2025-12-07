import subprocess
import os

def kill_existing(log=None):
    """
    Beendet laufende xwinwrap/mpv-Prozesse, die vom Wallpaper kommen.
    """
    def _log(msg: str):
        if log:
            log(msg)
        else:
            print(f"[wallpaper_engine] {msg}")

    for cmd in (
        ["pkill", "-f", "xwinwrap"],
        ["pkill", "-f", "mpv.*manifest.googlevideo.com"],
        ["pkill", "-f", "mpv.*DwKCna1mumk"],
        ["pkill", "-f", "mpv.*Cp4RRAEgpeU"],
    ):
        try:
            subprocess.run(cmd, check=False)
        except Exception as e:
            _log(f"Fehler beim Killen ({cmd}): {e}")

def start_wallpaper(geometry: str, url: str, log=None) -> None:
    """
    Startet xwinwrap + mpv im Hintergrund für einen Monitor.
    """
    def _log(msg: str):
        if log:
            log(msg)
        else:
            print(f"[wallpaper_engine] {msg}")

    env = os.environ.copy()
    env.setdefault("DISPLAY", ":0")

    _log(f"Starte xwinwrap/mpv mit Geometrie {geometry}")
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
