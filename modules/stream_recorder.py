#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
stream_recorder.py

Zentrale Funktionen für:
- Video-Aufnahme via yt-dlp + ffmpeg
- Screenshots via yt-dlp + ffmpeg
- Aufräumen von .mp4.part und Logs
- CLI-Interface:
    python3 -m modules.stream_recorder record URL TITLE [BROWSER]
    python3 -m modules.stream_recorder stop
    python3 -m modules.stream_recorder shot URL TITLE [BROWSER]
    python3 -m modules.stream_recorder cleanup
"""

import sys
import os
import json
import time
import signal
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

# Basis-Verzeichnisse
BASE_DIR = Path.home() / ".local" / "share" / "camwall"
RECORDINGS_DIR = BASE_DIR / "recordings"
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
RECORDER_LOG = BASE_DIR / "recorder.log"
ACTIVE_RECORDING_FILE = BASE_DIR / "active_recording.json"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _ensure_dirs() -> None:
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    BASE_DIR.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    try:
        _ensure_dirs()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with RECORDER_LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        # Logging darf nie das Programm komplett abschießen
        pass


# ---------------------------------------------------------------------------
# Kleine Hilfsfunktionen
# ---------------------------------------------------------------------------

def _safe_title_for_filename(title: str) -> str:
    """Titel in etwas Dateinamen-freundliches verwandeln."""
    base = (
        title.strip()
        .replace(" ", "_")
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
    cleaned = "".join(ch for ch in base if ch in allowed)
    return cleaned or "aufnahme"


def _write_active_recording(meta: Dict[str, Any]) -> None:
    try:
        _ensure_dirs()
        with ACTIVE_RECORDING_FILE.open("w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        log(f"Aktive Aufnahme geschrieben: {meta}")
    except Exception as e:
        log(f"Fehler beim Schreiben von ACTIVE_RECORDING_FILE: {e}")


def _read_active_recording() -> Optional[Dict[str, Any]]:
    if not ACTIVE_RECORDING_FILE.exists():
        return None
    try:
        with ACTIVE_RECORDING_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"Fehler beim Lesen von ACTIVE_RECORDING_FILE: {e}")
        return None


def _clear_active_recording() -> None:
    try:
        if ACTIVE_RECORDING_FILE.exists():
            ACTIVE_RECORDING_FILE.unlink()
            log("ACTIVE_RECORDING_FILE entfernt.")
    except Exception as e:
        log(f"Fehler beim Entfernen von ACTIVE_RECORDING_FILE: {e}")


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Prozess existiert, aber wir dürfen evtl. nicht signalisieren
        return True
    else:
        return True


# ---------------------------------------------------------------------------
# Cleanup-Funktion (Punkt 2 aus deinem Plan)
# ---------------------------------------------------------------------------

def cleanup_files() -> None:
    """
    - Löscht alle .mp4.part, die NICHT zur aktuell laufenden Aufnahme gehören.
    - Löscht leere .log-Dateien in recordings.
    - Kürzt recorder.log, wenn er zu groß wird.
    """
    _ensure_dirs()
    log("Cleanup: starte Bereinigung alter Dateien …")

    active = _read_active_recording()
    active_output = None
    if active and isinstance(active, dict):
        active_output = active.get("output_file")
        if active_output:
            active_output = str(active_output)

    # 1) .mp4.part aufräumen (außer ggf. der aktuellen Aufnahme)
    for part_file in RECORDINGS_DIR.glob("*.mp4.part"):
        try:
            part_str = str(part_file)
            # Wenn es eine aktive Aufnahme gibt und diese genau diese Datei nutzt -> behalten
            if active_output and part_str.startswith(active_output):
                log(f"Cleanup: überspringe laufende Part-Datei: {part_file}")
                continue

            part_file.unlink()
            log(f"Cleanup: verwaiste Part-Datei gelöscht: {part_file}")
        except Exception as e:
            log(f"Cleanup: Fehler beim Löschen von {part_file}: {e}")

    # 2) Leere Logs löschen
    for log_file in RECORDINGS_DIR.glob("*.log"):
        try:
            if log_file.stat().st_size == 0:
                log(f"Cleanup: leere Logdatei gelöscht: {log_file}")
                log_file.unlink()
        except Exception as e:
            log(f"Cleanup: Fehler beim Prüfen/Löschen von {log_file}: {e}")

    # 3) recorder.log einkürzen, falls zu groß (> 1 MB)
    try:
        if RECORDER_LOG.exists() and RECORDER_LOG.stat().st_size > 1_000_000:
            with RECORDER_LOG.open("r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            # Nur die letzten 500 Zeilen behalten
            keep = lines[-500:]
            with RECORDER_LOG.open("w", encoding="utf-8") as f:
                f.writelines(keep)
            # Wichtig: erst NACH dem Einkürzen loggen, sonst blähen wir wieder auf
            with RECORDER_LOG.open("a", encoding="utf-8") as f:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"[{ts}] Cleanup: recorder.log verkleinert (Rotation).\n")
    except Exception:
        # Im Zweifel ignorieren – der Recorder soll trotzdem funktionieren
        pass


# ---------------------------------------------------------------------------
# yt-dlp / ffmpeg Helper
# ---------------------------------------------------------------------------

def _build_yt_dlp_cmd(url: str, output_file: Path, browser: Optional[str]) -> list[str]:
    cmd = ["yt-dlp"]
    if browser:
        cmd += ["--cookies-from-browser", browser]
    # „best“ ist in deinem Fall OK – yt-dlp kümmert sich um HLS usw.
    cmd += ["-f", "best", "-o", str(output_file), url]
    return cmd


def _resolve_stream_url(url: str, browser: Optional[str]) -> str:
    """
    Verwendet yt-dlp, um die tatsächliche Stream-URL zu ermitteln (-g).
    Wird für Screenshots genutzt.
    """
    cmd = ["yt-dlp", "-g"]
    if browser:
        cmd += ["--cookies-from-browser", browser]
    cmd.append(url)

    log(f"resolve_stream_url: cmd={cmd}")
    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "yt-dlp wurde nicht gefunden. Bitte installiere das Paket 'yt-dlp'."
        )

    if result.returncode != 0 or not result.stdout.strip():
        err = (result.stderr or "").strip() or "unbekannter Fehler"
        raise RuntimeError(f"yt-dlp konnte die Stream-URL nicht ermitteln:\n{err}")

    # Letzte Zeile nehmen (manche Streams liefern mehrere Zeilen)
    return result.stdout.strip().splitlines()[-1]


# ---------------------------------------------------------------------------
# Öffentliche Funktionen für GUI + CLI
# ---------------------------------------------------------------------------

def start_recording(url: str, title: str, browser: Optional[str] = None) -> Dict[str, Any]:
    """
    Startet eine Aufnahme im Hintergrund (yt-dlp + ffmpeg).
    Gibt ein Dict mit Metadaten zurück.
    """
    _ensure_dirs()
    cleanup_files()  # vor jeder neuen Aufnahme aufräumen

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    safe_title = _safe_title_for_filename(title)
    output_file = RECORDINGS_DIR / f"{ts}_{safe_title}.mp4"
    log_file = RECORDINGS_DIR / f"{ts}_{safe_title}.log"

    cmd = _build_yt_dlp_cmd(url, output_file, browser)
    log(f"Starte Aufnahme mit Befehl: {' '.join(cmd)}")

    # yt-dlp-Ausgabe ins log_file umleiten
    log_fh = log_file.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        cmd,
        stdout=log_fh,
        stderr=log_fh,
    )

    meta: Dict[str, Any] = {
        "pid": proc.pid,
        "cmd": cmd,
        "output_file": str(output_file),
        "log_file": str(log_file),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "stream_url": url,
        "title": title,
    }
    if browser:
        meta["cookies_from_browser"] = browser

    _write_active_recording(meta)
    return meta


def stop_recording() -> bool:
    """
    Stoppt die aktuell laufende Aufnahme (falls vorhanden).
    Gibt True zurück, wenn etwas gestoppt wurde, sonst False.
    """
    _ensure_dirs()
    active = _read_active_recording()
    if not active:
        log("stop_recording: keine aktive Aufnahme gefunden.")
        return False

    pid = active.get("pid")
    if not isinstance(pid, int):
        log(f"stop_recording: 'pid' in active_recording ist ungültig: {pid}")
        _clear_active_recording()
        return False

    if not _process_exists(pid):
        log("stop_recording: Prozess existiert bereits nicht mehr.")
        _clear_active_recording()
        return False

    log(f"stop_recording: sende SIGINT an PID {pid}")
    try:
        os.kill(pid, signal.SIGINT)
    except Exception as e:
        log(f"stop_recording: Fehler beim Senden von SIGINT: {e}")
        # Trotzdem versuchen wir, die aktive Aufnahme aufzuräumen
        _clear_active_recording()
        return False

    # Kurz warten, bis der Prozess wirklich beendet ist
    for _ in range(50):  # max ~5 Sekunden
        time.sleep(0.1)
        if not _process_exists(pid):
            break

    if _process_exists(pid):
        log("stop_recording: Prozess läuft nach SIGINT noch – versuche SIGTERM.")
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception as e:
            log(f"stop_recording: Fehler beim Senden von SIGTERM: {e}")

    _clear_active_recording()
    log("stop_recording: Aufnahme gestoppt (oder war bereits beendet).")
    return True


def take_screenshot(url: str, title: str, browser: Optional[str] = None) -> Path:
    """
    Nimmt einen Screenshot des Streams auf:
    - ermittelt zuerst die Stream-URL via yt-dlp
    - holt dann mit ffmpeg ein Einzelbild
    """
    _ensure_dirs()
    cleanup_files()

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    safe_title = _safe_title_for_filename(title)
    out_path = SCREENSHOTS_DIR / f"{ts}_{safe_title}.png"
    log_file = SCREENSHOTS_DIR / f"{ts}_{safe_title}.log"

    # Stream-URL ermitteln (YouTube etc.)
    stream_url = _resolve_stream_url(url, browser)

    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-ss",
        "00:00:05",
        "-i",
        stream_url,
        "-vframes",
        "1",
        "-q:v",
        "2",
        str(out_path),
    ]

    log(f"take_screenshot: ffmpeg cmd={' '.join(cmd)}")

    try:
        with log_file.open("w", encoding="utf-8") as lf:
            proc = subprocess.run(cmd, check=False, stdout=lf, stderr=lf)
    except FileNotFoundError:
        raise RuntimeError(
            "ffmpeg wurde nicht gefunden. Bitte installiere das Paket 'ffmpeg'."
        )

    if proc.returncode != 0 or not out_path.exists():
        # Log-Inhalt für Fehlermeldung einlesen
        try:
            err_txt = log_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            err_txt = "Unbekannter Fehler (Log konnte nicht gelesen werden)."

        raise RuntimeError(
            "ffmpeg konnte keinen Screenshot erstellen.\n\nFehler:\n" + err_txt
        )

    log(f"Screenshot erstellt: {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# CLI-Einstiegspunkt
# ---------------------------------------------------------------------------

def _print_usage() -> None:
    print(
        "Verwendung:\n"
        "  python3 -m modules.stream_recorder record URL TITLE [BROWSER]\n"
        "  python3 -m modules.stream_recorder stop\n"
        "  python3 -m modules.stream_recorder shot URL TITLE [BROWSER]\n"
        "  python3 -m modules.stream_recorder cleanup\n"
    )


def main() -> None:
    _ensure_dirs()
    # Bei jedem Aufruf einmal kurz aufräumen – schadet nicht
    cleanup_files()

    if len(sys.argv) < 2:
        _print_usage()
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "record":
        if len(sys.argv) < 4:
            _print_usage()
            sys.exit(1)
        url = sys.argv[2]
        title = sys.argv[3]
        browser = sys.argv[4] if len(sys.argv) >= 5 else None

        meta = start_recording(url, title, browser)
        print("Aufnahme gestartet:")
        print(json.dumps(meta, ensure_ascii=False, indent=2))

    elif cmd == "stop":
        ok = stop_recording()
        if ok:
            print("Aufnahme gestoppt.")
        else:
            print("Aufnahme gestoppt (oder es lief keine Aufnahme).")

    elif cmd == "shot":
        if len(sys.argv) < 4:
            _print_usage()
            sys.exit(1)
        url = sys.argv[2]
        title = sys.argv[3]
        browser = sys.argv[4] if len(sys.argv) >= 5 else None

        try:
            path = take_screenshot(url, title, browser)
            print(f"Screenshot erstellt: {path}")
        except Exception as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)

    elif cmd == "cleanup":
        cleanup_files()
        print("Bereinigung abgeschlossen.")

    else:
        _print_usage()
        sys.exit(1)


if __name__ == "__main__":
    main()
