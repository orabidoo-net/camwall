import os
import signal
import shutil
import subprocess
import time
import threading
import shlex

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

MPV_BASE_ARGS = [
    "--no-config",
    "--no-audio",
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


def kill_existing(log, only: set[str] | None = None) -> None:
    """
    Beendet bestehende Wallpaper-Prozesse.
    Wenn `only` gesetzt ist, werden nur PID-Dateien für diese Monitor-IDs beendet.
    """
    for pidfile in PID_DIR.glob("*.pid"):
        mon_id = pidfile.stem

        if only is not None and mon_id not in only:
            continue

        try:
            pid = int(pidfile.read_text().strip())
        except Exception:
            pidfile.unlink(missing_ok=True)
            continue

        _log(log, f"Beende vorhandenen Wallpaper-Prozess PID {pid} (Datei: {pidfile.name})")
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

    mpv_args = " ".join(shlex.quote(a) for a in MPV_BASE_ARGS)
    script = f'echo "xwinwrap WID=$1" >&2; exec "$MPV" {mpv_args} --wid="$1" "$2"'

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
