import json
import os
import signal
import shutil
import socket
import subprocess
import time
import shlex
from typing import Iterable

from modules.paths import PID_DIR, LOG_PATH


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


def _send_ipc_quit(socket_path: str) -> None:
    if not os.path.exists(socket_path):
        return
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(0.2)
            client.connect(socket_path)
            msg = json.dumps({"command": ["quit"]}) + "\n"
            client.sendall(msg.encode("utf-8"))
    except Exception:
        pass


def _kill_pid_or_pgid(pid: int, sig: int) -> None:
    try:
        pgid = os.getpgid(pid)
        if pgid == pid:
            os.killpg(pgid, sig)
            return
    except Exception:
        pass
    os.kill(pid, sig)


def kill_existing(log, monitor_ids: Iterable[str] | None = None) -> None:
    """
    Beendet bestehende Wallpaper-Prozesse (xwinwrap samt mpv-Kindprozess)
    und räumt PID-Dateien sowie IPC-Sockets sauber auf.
    """
    targets = None
    if monitor_ids is not None:
        targets = set(str(x) for x in monitor_ids if x)

    mon_ids_to_clean: set[str] = set()
    for pidfile in PID_DIR.glob("*.pid"):
        mon_id = pidfile.stem
        if targets is None or mon_id in targets:
            mon_ids_to_clean.add(mon_id)

    if targets is not None:
        mon_ids_to_clean.update(targets)
    else:
        mon_ids_to_clean.update({"left", "right"})

    for mon_id in sorted(mon_ids_to_clean):
        pidfile = PID_DIR / f"{mon_id}.pid"
        socket_path = f"/tmp/camwall_{mon_id}.sock"
        pid = None

        if pidfile.exists():
            try:
                pid = int(pidfile.read_text().strip())
            except Exception:
                pidfile.unlink(missing_ok=True)

        # 1. mpv per IPC zum sauberen Beenden auffordern
        _send_ipc_quit(socket_path)

        # 2. Prozessgruppe aus PID-Datei mit SIGTERM beenden
        if pid is not None:
            _log(log, f"Beende vorhandenen Wallpaper-Prozess PID {pid} (Monitor {mon_id}, Datei: {pidfile.name})")
            try:
                _kill_pid_or_pgid(pid, signal.SIGTERM)
            except ProcessLookupError:
                _log(log, f"PID {pid} existiert nicht mehr.")
            except Exception as e:
                _log(log, f"SIGTERM für PID {pid} fehlgeschlagen: {e}")

        # 3. Verwaiste xwinwrap/mpv-Prozesse dieses Monitors anhand des eindeutigen
        #    Socket-Pfads im Kommandozeilen-Aufruf ebenfalls mit SIGTERM beenden
        try:
            subprocess.run(["pkill", "-TERM", "-f", socket_path], check=False)
        except Exception:
            pass

        # Bis zu 0.6s warten, damit xwinwrap und mpv sauber schließen können
        for _ in range(6):
            if pid is None or not _is_running(pid):
                break
            time.sleep(0.1)

        if pid is not None and _is_running(pid):
            _log(log, f"PID {pid} läuft noch, sende SIGKILL.")
            try:
                _kill_pid_or_pgid(pid, signal.SIGKILL)
            except Exception as e:
                _log(log, f"SIGKILL für PID {pid} fehlgeschlagen: {e}")

        try:
            subprocess.run(["pkill", "-KILL", "-f", socket_path], check=False)
        except Exception:
            pass

        pidfile.unlink(missing_ok=True)

        # Alten IPC-Socket des Monitors aufräumen
        try:
            if os.path.exists(socket_path):
                os.remove(socket_path)
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

    # Wichtig: Keine offene stderr-Pipe an den kurzlebigen camwall-apply-Prozess
    # binden (sonst stirbt der Lese-Thread beim Ende von camwall-apply und
    # xwinwrap/mpv erhalten später SIGPIPE). Zudem start_new_session=True,
    # damit xwinwrap und mpv eine eigene Prozessgruppe bilden, die komplett
    # über os.killpg beendet werden kann.
    stderr_fh = None
    try:
        if WALLPAPER_DEBUG:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            stderr_fh = LOG_PATH.open("a", encoding="utf-8")
            stderr_target = stderr_fh
        else:
            stderr_target = subprocess.DEVNULL

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=stderr_target,
            text=True,
            env=env,
            start_new_session=True,
        )
    finally:
        if stderr_fh is not None:
            try:
                stderr_fh.close()
            except Exception:
                pass

    time.sleep(0.1)
    if proc.poll() is not None:
        _log(log, f"xwinwrap exited immediately (code {proc.returncode})")
        return

    try:
        pidfile = PID_DIR / f"{monitor_id}.pid"
        pidfile.write_text(str(proc.pid))
    except Exception as e:
        _log(log, f"Konnte PID-Datei nicht schreiben: {e}")
