#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
stream_recorder.py
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

from modules.paths import CONFIG_PATH

# Basis-Verzeichnisse
BASE_DIR = Path.home() / ".local" / "share" / "camwall"
RECORDINGS_DIR = BASE_DIR / "recordings"
RECORDER_LOG = BASE_DIR / "recorder.log"
ACTIVE_RECORDING_FILE = BASE_DIR / "active_recording.json"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _ensure_dirs() -> None:
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    BASE_DIR.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    try:
        _ensure_dirs()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with RECORDER_LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Kleine Hilfsfunktionen
# ---------------------------------------------------------------------------

def _safe_title_for_filename(title: str) -> str:
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
    except Exception as e:
        log(f"Fehler beim Schreiben von ACTIVE_RECORDING_FILE: {e}")


def _read_active_recording() -> Optional[Dict[str, Any]]:
    if not ACTIVE_RECORDING_FILE.exists():
        return None
    try:
        with ACTIVE_RECORDING_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _clear_active_recording() -> None:
    try:
        if ACTIVE_RECORDING_FILE.exists():
            ACTIVE_RECORDING_FILE.unlink()
    except Exception:
        pass


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    else:
        return True


def cleanup_files() -> None:
    _ensure_dirs()
    active = _read_active_recording()
    active_output = None
    if active and isinstance(active, dict):
        active_output = active.get("output_file")
        if active_output:
            active_output = str(active_output)

    for part_file in RECORDINGS_DIR.glob("*.mp4.part"):
        try:
            part_str = str(part_file)
            if active_output and part_str.startswith(active_output):
                continue
            part_file.unlink()
        except Exception:
            pass

    for log_file in RECORDINGS_DIR.glob("*.log"):
        try:
            if log_file.stat().st_size == 0:
                log_file.unlink()
        except Exception:
            pass

    try:
        if RECORDER_LOG.exists() and RECORDER_LOG.stat().st_size > 1_000_000:
            with RECORDER_LOG.open("r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            keep = lines[-500:]
            with RECORDER_LOG.open("w", encoding="utf-8") as f:
                f.writelines(keep)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Intelligente Ermittlung des Stream-Typs
# ---------------------------------------------------------------------------

def _get_stream_type(url: str) -> str:
    try:
        if CONFIG_PATH.exists():
            with CONFIG_PATH.open("r", encoding="utf-8") as f:
                config = json.load(f)
            for sid, s in config.get("streams", {}).items():
                if s.get("url") == url:
                    return s.get("type", "youtube")
    except Exception:
        pass
    return "youtube"


# ---------------------------------------------------------------------------
# yt-dlp Helper
# ---------------------------------------------------------------------------

def _build_yt_dlp_cmd(url: str, output_file: Path, browser: Optional[str]) -> list[str]:
    cmd = ["yt-dlp"]
    stype = _get_stream_type(url)
    
    if stype == "youtube_cookies" and browser:
        cmd += ["--cookies-from-browser", browser]
        
    cmd += ["-f", "best", "-o", str(output_file), url]
    return cmd


# ---------------------------------------------------------------------------
# Öffentliche Funktionen für GUI + CLI
# ---------------------------------------------------------------------------

def start_recording(url: str, title: str, browser: Optional[str] = None) -> Dict[str, Any]:
    _ensure_dirs()
    cleanup_files()

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    safe_title = _safe_title_for_filename(title)
    output_file = RECORDINGS_DIR / f"{ts}_{safe_title}.mp4"
    log_file = RECORDINGS_DIR / f"{ts}_{safe_title}.log"

    cmd = _build_yt_dlp_cmd(url, output_file, browser)
    log_fh = log_file.open("w", encoding="utf-8")
    proc = subprocess.Popen(cmd, stdout=log_fh, stderr=log_fh)

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
    _ensure_dirs()
    active = _read_active_recording()
    if not active:
        return False

    pid = active.get("pid")
    if not isinstance(pid, int):
        _clear_active_recording()
        return False

    if not _process_exists(pid):
        _clear_active_recording()
        return False

    try:
        os.kill(pid, signal.SIGINT)
    except Exception:
        _clear_active_recording()
        return False

    for _ in range(50):
        time.sleep(0.1)
        if not _process_exists(pid):
            break

    if _process_exists(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass

    _clear_active_recording()
    return True


# ---------------------------------------------------------------------------
# CLI-Einstiegspunkt
# ---------------------------------------------------------------------------

def _print_usage() -> None:
    print(
        "Verwendung:\n"
        "  python3 -m modules.stream_recorder record URL TITLE [BROWSER]\n"
        "  python3 -m modules.stream_recorder stop\n"
        "  python3 -m modules.stream_recorder cleanup\n"
    )

def main() -> None:
    _ensure_dirs()
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

    elif cmd == "cleanup":
        cleanup_files()
        print("Bereinigung abgeschlossen.")

    else:
        _print_usage()
        sys.exit(1)

if __name__ == "__main__":
    main()
