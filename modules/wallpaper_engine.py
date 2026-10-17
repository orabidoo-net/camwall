import os
import signal
import shutil
import subprocess
import time
import threading
import shlex
from typing import Iterable

from modules.paths import PID_DIR


# ---- zentrale Defaults -------------------------------------------------------

# Bei dir verursacht -ov ein X11 BadMatch, daher hier bewusst NICHT enthalten.
XWINWRAP_BASE_ARGS = [
    "-ni",
    "-un",
    "-fdt",
    "-s",
    "-st",
    "-sp",
    "-b",
    "-nf",
]

# Hinweis: --no-audio haben wir hier entfernt! 
# mpv startet stattdessen standardmäßig mit Ton, aber WIR schalten ihn im Shell-Skript 
# sofort stumm (--mute=yes). So können wir ihn später per IPC wieder einschalten.
MPV_BASE_ARGS = [
    "--no-config",
    "--loop=inf",
    "--no-border",
    "--no-osc",
    "--no-input-default-bindings",
    "--really-quiet",
]

# Setze CAMWALL_WALLPAPER_DEBUG=1 um komplette stderr-Ausgaben zu loggen.
WALLPAPER_DEBUG = os.environ.get("CAMWALL_WALLPAPER_DEBUG", "0") == "1"


def _log(log, msg: str) -> None:
    if log:
        log(msg)


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def kill_existing(log, monitor_ids: Iterable[str] | None = None) -> None:
    """
    Beendet bestehende Wallpaper-Prozesse und räumt IPC-Sockets auf.
    """
    targets = None
    if monitor_ids is not None:
        targets = set(str(x) for x in monitor_ids)

    for pidfile in PID_DIR.glob("*.pid"):
        mon_id = pidfile.stem
        if targets is not None and mon_id not in targets:
            continue

        try:
            pid = int(pidfile.read_text().strip())
        except Exception:
            pidfile.unlink(missing_ok=True)
            continue

        _log(log, f"Beende vorhandenen Wallpaper-Prozess PID {pid} (Monitor {mon_id}, Datei: {pidfile.name})")
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            _log(log, f"PID {pid} existiert nicht mehr.")
        except Exception as e:
            _log(log, f"SIGTERM für PID {pid} fehlgeschlagen: {e}")

        time.sleep(0.3)

        if _is_running(pid):
            _log(log, f"PID {pid} läuft noch, sende SIGKILL.")
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception as e:
                _log(log, f"SIGKILL für PID {pid} fehlgeschlagen: {e}")

        pidfile.unlink(missing_ok=True)
        
        # Alten IPC-Socket des Monitors aufräumen
        socket_path = f"/tmp/camwall_{mon_id}.sock"
        try:
            if os.path.exists(socket_path):
                os.remove(socket_path)
        except Exception:
            pass


def _stderr_worker(proc: subprocess.Popen, log, monitor_id: str) -> None:
    """
    Liest stderr kontinuierlich, damit der Pipe nicht vollläuft.
    Loggt standardmäßig nur die WID-Zeile; im Debug-Modus alles.
    """
    try:
        for line in proc.stderr:
            line = (line or "").strip()
            if not line:
                continue
            if ("xwinwrap WID=" in line) or WALLPAPER_DEBUG:
                _log(log, f"[{monitor_id}] {line}")
    except Exception:
        pass


def start_wallpaper(monitor_id: str, geometry: str, url: str, log) -> None:
    xwinwrap_path = "/usr/local/bin/xwinwrap" if os.path.exists("/usr/local/bin/xwinwrap") else shutil.which("xwinwrap")
    mpv_path = "/usr/bin/mpv" if os.path.exists("/usr/bin/mpv") else shutil.which("mpv")

    if not xwinwrap_path:
        _log(log, "xwinwrap nicht gefunden, breche ab.")
        return
    if not mpv_path:
        _log(log, "mpv nicht gefunden, breche ab.")
        return

    socket_path = f"/tmp/camwall_{monitor_id}.sock"

    # Shell-Skript:
    # 1. Wir aktivieren den IPC Server (die "Fernbedienung").
    # 2. Wir starten initial mit --mute=yes (Ton ist da, aber stummgeschaltet, bereit zum Unmuten!).
    mpv_args = " ".join(shlex.quote(a) for a in MPV_BASE_ARGS)
    script = f'echo "xwinwrap WID=$1" >&2; exec "$MPV" {mpv_args} --mute=yes --input-ipc-server="{socket_path}" --wid="$1" "$2"'

    cmd = [
        xwinwrap_path,
        "-g", geometry,
        *XWINWRAP_BASE_ARGS,
        "--",
        "sh", "-c", script,
        "sh", "WID", url,
    ]

    env = dict(os.environ)
    env["MPV"] = mpv_path

    _log(log, f"Starte Wallpaper für Monitor {monitor_id} mit Geometrie {geometry}")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    if proc.poll() is not None:
        try:
            err = proc.stderr.read() if proc.stderr else ""
        except Exception:
            err = ""
        _log(log, f"xwinwrap exited immediately (code {proc.returncode}): {err.strip()}")
        return

    t = threading.Thread(target=_stderr_worker, args=(proc, log, monitor_id), daemon=True)
    t.start()

    try:
        pidfile = PID_DIR / f"{monitor_id}.pid"
        pidfile.write_text(str(proc.pid))
    except Exception as e:
        _log(log, f"Konnte PID-Datei nicht schreiben: {e}")
