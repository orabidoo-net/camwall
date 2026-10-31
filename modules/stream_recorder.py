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
import threading
import traceback
import fcntl
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from modules.paths import CONFIG_PATH

BASE_DIR = Path.home() / ".local" / "share" / "camwall"
RECORDINGS_DIR = BASE_DIR / "recordings"
RECORDER_LOG = BASE_DIR / "recorder.log"
# HISTORISCH: Früher gab es eine einzige, gemeinsam genutzte
# active_recording.json für ALLE Monitore. Da links und rechts als zwei
# komplett unabhängige camwall-overlay.py-Prozesse laufen, kam es beim
# gleichzeitigen Start/Stop (bzw. bei einem Watchdog-Neustart kurz nach dem
# App-Start) zu verlorenen Schreibvorgängen: Prozess A liest die Datei,
# Prozess B liest sie ebenfalls, dann schreibt A seinen Eintrag, und B
# überschreibt die Datei direkt danach OHNE A's Eintrag - A's Aufnahme galt
# damit als "nicht aktiv", obwohl sie lief. Genau das war die Ursache dafür,
# dass die erste Aufnahme eines Monitors im Media-Tab/Ordner fehlte.
#
# Lösung: Jeder Monitor (instance_id) bekommt jetzt seine EIGENE State-Datei.
# Dadurch gibt es keine gemeinsam genutzte Ressource mehr, um die zwei
# Prozesse konkurrieren könnten.
ACTIVE_RECORDING_DIR = BASE_DIR / "active_recordings"


def _ensure_dirs() -> None:
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    ACTIVE_RECORDING_DIR.mkdir(parents=True, exist_ok=True)


def _active_file_for(instance_id: str) -> Path:
    safe_id = "".join(ch for ch in instance_id if ch.isalnum() or ch in "_-") or "default"
    return ACTIVE_RECORDING_DIR / f"{safe_id}.json"


@contextmanager
def _instance_lock(instance_id: str):
    """
    Sperrt ausschließlich die State-Datei EINES Monitors. Da jeder Monitor
    seine eigene Datei hat, blockiert das Sperren von 'left' niemals den
    Zugriff auf 'right' und umgekehrt.
    """
    _ensure_dirs()
    lock_path = _active_file_for(instance_id).with_suffix(".lock")
    with lock_path.open("w") as lock_fh:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)


def log(msg: str) -> None:
    try:
        _ensure_dirs()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with RECORDER_LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


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


def _read_instance_recording(instance_id: str) -> Optional[Dict[str, Any]]:
    """Liest den State EINES Monitors aus dessen eigener Datei."""
    path = _active_file_for(instance_id)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else None
    except Exception:
        return None


def _write_instance_recording(instance_id: str, meta: Optional[Dict[str, Any]]) -> None:
    """
    Schreibt (oder löscht, falls meta None ist) den State EINES Monitors.
    Jeder Monitor hat seine eigene Datei - daher kein Risiko mehr, dass
    ein anderer Monitor-Prozess diesen Eintrag überschreibt.
    """
    try:
        _ensure_dirs()
        path = _active_file_for(instance_id)
        if meta is None:
            path.unlink(missing_ok=True)
            return
        with path.open("w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"Fehler beim Schreiben der Aufnahme-State-Datei ({instance_id}): {e}")


def _reap_zombie_if_child(pid: int) -> bool:
    """
    Erntet einen beendeten Kindprozess (Zombie), falls `pid` ein direkter
    Kindprozess des aktuellen Prozesses ist. Gibt True zurück, wenn der
    Prozess bereits beendet war und geerntet wurde.
    """
    try:
        wpid, _ = os.waitpid(pid, os.WNOHANG)
        if wpid == pid:
            return True
    except ChildProcessError:
        pass
    except Exception:
        pass
    return False


def _is_recording_process_alive(pid: Any, expected_output: Optional[str] = None) -> bool:
    """
    Prüft strikt anhand von /proc, ob `pid` tatsächlich existiert, KEIN Zombie
    ist und ein echter yt-dlp/ffmpeg-Aufnahmeprozess (für `expected_output`) ist.
    Verhindert zuverlässig Geister-Status durch verwaiste JSON-Dateien,
    Zombie-Prozesse oder vom Betriebssystem wiederverwendete PIDs.
    """
    if not isinstance(pid, int) or pid <= 0:
        return False

    if _reap_zombie_if_child(pid):
        return False

    proc_dir = Path(f"/proc/{pid}")
    if not proc_dir.exists():
        return False

    # 1. Zombie-/Dead-Status in /proc/<pid>/stat ausschließen
    try:
        stat_text = (proc_dir / "stat").read_text(encoding="utf-8", errors="ignore")
        after_comm = stat_text.rsplit(")", 1)[-1].strip()
        state_char = after_comm.split()[0] if after_comm else ""
        if state_char in ("Z", "X", "x"):
            _reap_zombie_if_child(pid)
            return False
    except FileNotFoundError:
        return False
    except Exception:
        pass

    # 2. Kommandozeile prüfen (Schutz gegen PID-Recycling nach Neustart)
    try:
        raw_cmdline = (proc_dir / "cmdline").read_bytes()
        cmdline = raw_cmdline.replace(b"\x00", b" ").decode("utf-8", errors="ignore").strip()
        if not cmdline:
            return False
        if "yt-dlp" not in cmdline and "ffmpeg" not in cmdline:
            return False
        if expected_output:
            out_name = Path(str(expected_output)).name
            if out_name and out_name not in cmdline:
                return False
    except FileNotFoundError:
        return False
    except Exception:
        pass

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_exists(pid: int) -> bool:
    return _is_recording_process_alive(pid)


def _read_log_tail(log_file: Optional[Path | str], max_chars: int = 2000) -> str:
    if not log_file:
        return ""
    try:
        p = Path(log_file)
        if not p.exists():
            return ""
        content = p.read_text(encoding="utf-8", errors="replace").strip()
        if len(content) > max_chars:
            return "... " + content[-max_chars:]
        return content
    except Exception as e:
        return f"(Logdatei konnte nicht gelesen werden: {e})"


def _is_any_helper_alive_for_stem(stem: str) -> bool:
    """
    Prüft in /proc, ob noch ein nachgelagerter ffmpeg/yt-dlp-Prozess (z. B. der
    Fixup-PostProcessor zum Muxen nach .temp.mp4) auf Dateien mit `stem` arbeitet.
    """
    if not stem:
        return False
    for proc_entry in Path("/proc").iterdir():
        if not proc_entry.name.isdigit():
            continue
        pid = int(proc_entry.name)
        try:
            stat_text = (proc_entry / "stat").read_text(encoding="utf-8", errors="ignore")
            after_comm = stat_text.rsplit(")", 1)[-1].strip()
            state_char = after_comm.split()[0] if after_comm else ""
            if state_char in ("Z", "X", "x"):
                continue
            raw_cmdline = (proc_entry / "cmdline").read_bytes()
            cmdline = raw_cmdline.replace(b"\x00", b" ").decode("utf-8", errors="ignore")
            if stem in cmdline and ("ffmpeg" in cmdline or "yt-dlp" in cmdline):
                return True
        except Exception:
            continue
    return False


def _kill_helpers_for_stem(stem: str, sig: int) -> None:
    if not stem:
        return
    for proc_entry in Path("/proc").iterdir():
        if not proc_entry.name.isdigit():
            continue
        pid = int(proc_entry.name)
        try:
            raw_cmdline = (proc_entry / "cmdline").read_bytes()
            cmdline = raw_cmdline.replace(b"\x00", b" ").decode("utf-8", errors="ignore")
            if stem in cmdline and ("ffmpeg" in cmdline or "yt-dlp" in cmdline):
                os.kill(pid, sig)
        except Exception:
            continue


def _finalize_part_file(output_file: Optional[str]) -> None:
    """
    Bereinigt und finalisiert sämtliche temporären Aufnahmedateien (.mp4.part,
    .temp.mp4, .mp4.temp, .temp.mp4.part, .ytdl, Fragment-Dateien) nach dem
    Ende/Stoppen eines Aufnahmeprozesses.
    Garantiert, dass am Ende genau EINE saubere .mp4-Datei übrig bleibt und
    keine .temp.mp4- oder .part-Reste zurückbleiben.
    """
    if not output_file:
        return

    try:
        out_path = Path(str(output_file))
        parent = out_path.parent
        stem = out_path.stem  # z. B. "2026-10-30_22-30-00_Monitor_Stream"

        if not parent.exists() or not stem:
            return

        temp_mp4 = parent / f"{stem}.temp.mp4"
        mp4_temp = parent / f"{stem}.mp4.temp"
        part_file = parent / f"{stem}.mp4.part"
        temp_part_file = parent / f"{stem}.temp.mp4.part"

        # Alle weiteren temporären Kandidaten zu diesem Basisnamen ermitteln
        extra_temp_files: list[Path] = []
        for cand in parent.glob(f"{stem}.*"):
            if cand == out_path:
                continue
            if cand.suffix.lower() in (".log", ".png"):
                continue
            extra_temp_files.append(cand)

        def _safe_size(p: Path) -> int:
            try:
                return p.stat().st_size if p.exists() else 0
            except Exception as e:
                log(f"_finalize_part_file: stat() fehlgeschlagen für {p.name}: {e}")
                return 0

        out_size = _safe_size(out_path)
        temp_mp4_size = _safe_size(temp_mp4)

        # Fall 1: Die finale .mp4 existiert bereits und hat Inhalt
        if out_size > 0:
            # Wenn parallel noch eine .temp.mp4 (vom yt-dlp Fixup/Remux) existiert:
            # Ist .temp.mp4 mindestens so groß wie .mp4, war das Remuxen fertig
            # und nur das letzte Rename von yt-dlp wurde unterbrochen -> ersetzen.
            # Ist .temp.mp4 kleiner/unvollständig, wurde der Remux-Schritt mitten
            # im Schreiben abgebrochen -> die intakte .mp4 behalten und .temp.mp4 löschen!
            if temp_mp4.exists():
                try:
                    if temp_mp4_size >= out_size and temp_mp4_size > 0:
                        os.replace(temp_mp4, out_path)
                        log(
                            f"Finalisierung: Fertige {temp_mp4.name} ({temp_mp4_size} B) "
                            f"hat {out_path.name} ({out_size} B) ersetzt."
                        )
                    else:
                        temp_mp4.unlink(missing_ok=True)
                        log(
                            f"Finalisierung: Unvollständige {temp_mp4.name} ({temp_mp4_size} B) "
                            f"gelöscht, behalte intakte {out_path.name} ({out_size} B)."
                        )
                except Exception as e:
                    log(f"Fehler beim Auflösen von {temp_mp4.name} gegen {out_path.name}: {e}")

        # Fall 2: Finale .mp4 existiert NICHT (oder ist 0 Bytes groß)
        else:
            if out_path.exists():
                try:
                    out_path.unlink(missing_ok=True)
                except Exception as e:
                    log(f"Konnte leere Zieldatei {out_path.name} nicht entfernen: {e}")

            # Beste nicht-leere temporäre Videodatei suchen und in .mp4 umbenennen
            candidates = [temp_mp4, part_file, mp4_temp, temp_part_file]
            for c in extra_temp_files:
                if c not in candidates and not c.name.endswith(".ytdl"):
                    candidates.append(c)

            best_cand: Optional[Path] = None
            best_size = 0
            for cand in candidates:
                csize = _safe_size(cand)
                if csize > best_size:
                    best_size = csize
                    best_cand = cand

            if best_cand is not None and best_size > 0:
                try:
                    os.replace(best_cand, out_path)
                    log(
                        f"Manuelle Rettung: {best_cand.name} ({best_size} B) "
                        f"sauber in {out_path.name} umbenannt."
                    )
                except Exception as e:
                    log(f"Fehler beim Umbenennen von {best_cand.name} nach {out_path.name}: {e}")

        # Abschließend ALLE verbliebenen temporären Dateien (.temp.mp4, .part, .ytdl usw.)
        # für diesen Aufnahme-Stem garantiert löschen
        for leftover in parent.glob(f"{stem}.*"):
            if leftover == out_path or leftover.suffix.lower() in (".log", ".png"):
                continue
            try:
                leftover.unlink(missing_ok=True)
                log(f"Temporäre Datei bereinigt: {leftover.name}")
            except Exception as e:
                log(f"Fehler beim Löschen der temporären Datei {leftover.name}: {e}")

    except Exception as e:
        log(f"Unerwarteter Fehler in _finalize_part_file({output_file}): {e}\n{traceback.format_exc()}")


def _find_orphan_recording_meta(instance_id: str) -> Optional[Dict[str, Any]]:
    """
    Sucht in /proc nach einem laufenden yt-dlp-Aufnahmeprozess für `instance_id`
    (anhand der Umgebungsvariable CAMWALL_RECORD_INSTANCE), falls die JSON-Datei
    fälschlich gelöscht wurde, während der Prozess im Hintergrund weiterläuft.
    """
    target_env = f"CAMWALL_RECORD_INSTANCE={instance_id}".encode("utf-8")
    for proc_entry in Path("/proc").iterdir():
        name = proc_entry.name
        if not name.isdigit():
            continue
        pid = int(name)
        try:
            comm = (proc_entry / "comm").read_text(encoding="utf-8", errors="ignore").strip()
            if comm != "yt-dlp":
                continue
            environ_bytes = (proc_entry / "environ").read_bytes()
            if target_env not in environ_bytes.split(b"\x00"):
                continue
            if not _is_recording_process_alive(pid):
                continue
            raw_args = [
                a.decode("utf-8", errors="ignore")
                for a in (proc_entry / "cmdline").read_bytes().split(b"\x00")
                if a
            ]
            output_file = ""
            if "-o" in raw_args:
                idx = raw_args.index("-o")
                if idx + 1 < len(raw_args):
                    output_file = raw_args[idx + 1]
            return {
                "pid": pid,
                "cmd": raw_args,
                "output_file": output_file,
                "recovered": True,
            }
        except Exception:
            continue
    return None


def get_active_recording(instance_id: str = "default") -> Optional[Dict[str, Any]]:
    """
    Gibt die Metadaten der laufenden Aufnahme für `instance_id` zurück, ABER NUR
    wenn der zugehörige Aufnahmeprozess tatsächlich im Hintergrund lebt.
    Abgestorbene/verwaiste State-Dateien werden sofort bereinigt.
    """
    _ensure_dirs()
    meta = _read_instance_recording(instance_id)
    if meta:
        pid = meta.get("pid")
        output_file = meta.get("output_file")
        log_file = meta.get("log_file")
        if _is_recording_process_alive(pid, output_file):
            return meta

        # Der Prozess aus der State-Datei existiert nicht mehr -> Details loggen,
        # State-Datei und eventuelle .part/.temp.mp4-Datei sofort bereinigen!
        log_tail = _read_log_tail(log_file)
        log(
            f"Bereinige verwaisten Aufnahme-Status für '{instance_id}' "
            f"(PID {pid} läuft nicht mehr)."
            + (f" Letzte Prozess-Ausgabe:\n{log_tail}" if log_tail else "")
        )
        _finalize_part_file(output_file)
        with _instance_lock(instance_id):
            current = _read_instance_recording(instance_id)
            if current and current.get("pid") == pid:
                _write_instance_recording(instance_id, None)

    # Prüfen, ob ein Aufnahmeprozess für diesen Monitor ohne State-Datei läuft,
    # und falls ja, die State-Datei wiederherstellen.
    orphan_meta = _find_orphan_recording_meta(instance_id)
    if orphan_meta:
        with _instance_lock(instance_id):
            _write_instance_recording(instance_id, orphan_meta)
        return orphan_meta

    return None


def is_recording_active(instance_id: str = "default") -> bool:
    """
    Gibt strikt True zurück, wenn für `instance_id` ein echter Aufnahmeprozess
    läuft, andernfalls False (inkl. automatischer Bereinigung alter State-Dateien).
    """
    return get_active_recording(instance_id) is not None


def _read_active_recording() -> Dict[str, Any]:
    """
    Liest den validierten State ALLER Monitore (nur tatsächlich laufende
    Aufnahmeprozesse). Verwaiste JSON-Dateien von beendeten Prozessen werden
    automatisch entfernt.
    """
    _ensure_dirs()
    result: Dict[str, Any] = {}
    instance_ids = {path.stem for path in ACTIVE_RECORDING_DIR.glob("*.json")}
    instance_ids.update({"left", "right"})

    for instance_id in sorted(instance_ids):
        meta = get_active_recording(instance_id)
        if meta:
            result[instance_id] = meta
    return result


def cleanup_files() -> None:
    _ensure_dirs()
    active_all = _read_active_recording()
    active_stems: set[str] = set()

    for meta in active_all.values():
        if isinstance(meta, dict) and meta.get("output_file"):
            active_stems.add(Path(str(meta.get("output_file"))).stem)

    # Nicht mehr aktive .part / .temp.mp4 / .mp4.temp Dateien sauber finalisieren bzw. aufräumen
    temp_patterns = ("*.mp4.part", "*.temp.mp4", "*.mp4.temp", "*.temp.mp4.part", "*.ytdl")
    seen_stems: set[str] = set()
    for pattern in temp_patterns:
        for tmp_file in RECORDINGS_DIR.glob(pattern):
            try:
                name = tmp_file.name
                base_stem = name.split(".")[0]
                if base_stem in active_stems or base_stem in seen_stems:
                    continue
                seen_stems.add(base_stem)
                _finalize_part_file(str(RECORDINGS_DIR / f"{base_stem}.mp4"))
            except Exception as e:
                log(f"cleanup_files: Fehler bei {tmp_file.name}: {e}")

    for log_file in RECORDINGS_DIR.glob("*.log"):
        try:
            if log_file.stat().st_size == 0 and log_file.stem not in active_stems:
                log_file.unlink(missing_ok=True)
        except Exception:
            pass


def _get_stream_type(url: str) -> str:
    clean_url = (url or "").strip()
    try:
        if CONFIG_PATH.exists():
            with CONFIG_PATH.open("r", encoding="utf-8") as f:
                config = json.load(f)
            for sid, s in config.get("streams", {}).items():
                if (s.get("url") or "").strip() == clean_url:
                    return s.get("type", "youtube")
    except Exception as e:
        log(f"_get_stream_type: Fehler beim Lesen von {CONFIG_PATH}: {e}")
    return "youtube"


def _build_yt_dlp_cmd(url: str, output_file: Path, browser: Optional[str]) -> list[str]:
    # Wichtig: KEIN --quiet / --no-warnings mehr, damit Start-Abstürze (z. B.
    # Cookie-Fehler, Format-Fehler, Netzwerkprobleme) vollständig in die Logdatei
    # geschrieben und von unserem Error-Handler ausgewertet werden können!
    cmd = [
        "yt-dlp",
        "--newline",
        "--no-progress",
        "--fragment-retries", "10",
        "--downloader-args", "ffmpeg:-loglevel warning",
    ]
    stype = _get_stream_type(url)

    # Wenn der Aufrufer einen Browser übergibt (oder der Stream als youtube_cookies
    # konfiguriert ist), immer Cookies aktivieren.
    if browser and stype in ("youtube_cookies", "youtube"):
        cmd += ["--cookies-from-browser", browser]

    # Flexibler Format-Selector mit Fallback: Manche YouTube-Livestreams bieten
    # kein einzelnes kombiniertes "best"-Format an und stürzen bei "-f best"
    # sofort mit "Requested format is not available" ab, ohne eine Datei anzulegen.
    cmd += [
        "-f", "best/bestvideo*+bestaudio",
        "--merge-output-format", "mp4",
        "-o", str(output_file),
        url,
    ]
    return cmd


def _kill_recording_tree(pid: int, sig: int) -> None:
    try:
        pgid = os.getpgid(pid)
        if pgid == pid:
            os.killpg(pgid, sig)
            return
    except Exception:
        pass
    os.kill(pid, sig)


def _watch_recording_process(
    proc: subprocess.Popen,
    instance_id: str,
    output_file: str,
    log_file: Path,
) -> None:
    """
    Hintergrund-Wächter-Thread für einen gestarteten Aufnahmeprozess:
    1. Erntet den Prozess sofort per proc.wait(), sobald er endet (verhindert Zombies).
    2. Falls der Prozess unerwartet (ohne regulären Stop-Befehl) abstürzt, wird
       die Ursache samt yt-dlp/ffmpeg-Logausgabe detailliert in recorder.log
       protokolliert und der verwaiste Status sowie temporäre Dateien bereinigt.
    """
    try:
        rc = proc.wait()
        current = _read_instance_recording(instance_id)
        is_expected_stop = bool(current and current.get("stopping"))

        if not is_expected_stop:
            log_tail = _read_log_tail(log_file)
            out_exists = Path(output_file).exists()
            log(
                f"WARNUNG/ABSTURZ: Aufnahmeprozess auf Monitor '{instance_id}' "
                f"(PID {proc.pid}) wurde unerwartet beendet (Exit-Code {rc}, "
                f"Zieldatei existiert: {out_exists}).\n"
                f"--- Prozess-Log ({log_file.name}) ---\n"
                f"{log_tail or '(keine Ausgabe in Logdatei)'}\n"
                f"--- Ende Prozess-Log ---"
            )
            _finalize_part_file(output_file)
            with _instance_lock(instance_id):
                latest = _read_instance_recording(instance_id)
                if latest and latest.get("pid") == proc.pid and not latest.get("stopping"):
                    _write_instance_recording(instance_id, None)
    except Exception as e:
        log(f"Fehler im Aufnahme-Wächter-Thread ({instance_id}, PID {proc.pid}): {e}\n{traceback.format_exc()}")


def start_recording(url: str, title: str, browser: Optional[str] = None, instance_id: str = "default") -> Dict[str, Any]:
    try:
        _ensure_dirs()

        # Falls auf diesem Monitor bereits eine Aufnahme läuft, diese zuerst sauber stoppen,
        # damit niemals ein alter Aufnahmeprozess verwaist im Hintergrund weiterläuft.
        if is_recording_active(instance_id):
            log(f"start_recording ({instance_id}): Stoppe zuerst noch laufende Aufnahme...")
            stop_recording(instance_id)

        cleanup_files()

        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_title = _safe_title_for_filename(title)
        output_file = RECORDINGS_DIR / f"{ts}_{safe_title}.mp4"
        log_file = RECORDINGS_DIR / f"{ts}_{safe_title}.log"

        cmd = _build_yt_dlp_cmd(url, output_file, browser)
        env = dict(os.environ)
        env["CAMWALL_RECORD_INSTANCE"] = instance_id

        log(
            f"start_recording ({instance_id}): Starte Aufnahme\n"
            f"  URL:    {url}\n"
            f"  Ziel:   {output_file}\n"
            f"  Log:    {log_file}\n"
            f"  Befehl: {' '.join(cmd)}"
        )

        log_fh = None
        try:
            log_fh = log_file.open("w", encoding="utf-8")
            proc = subprocess.Popen(
                cmd,
                stdout=log_fh,
                stderr=log_fh,
                env=env,
                start_new_session=True,
            )
        except Exception as spawn_err:
            log(
                f"FEHLER beim Starten des Aufnahme-Subprozesses ({instance_id}): "
                f"{spawn_err}\n{traceback.format_exc()}"
            )
            raise RuntimeError(f"Aufnahmeprozess konnte nicht gestartet werden: {spawn_err}") from spawn_err
        finally:
            if log_fh is not None:
                try:
                    log_fh.close()
                except Exception:
                    pass

        # Sofort-Check (bis zu 1.0s) auf unmittelbare Start-Abstürze
        for _ in range(10):
            time.sleep(0.1)
            if proc.poll() is not None:
                break

        if proc.poll() is not None:
            log_tail = _read_log_tail(log_file)
            log(
                f"START-ABSTURZ der Aufnahme ({instance_id}, PID {proc.pid}, "
                f"Exit-Code {proc.returncode}):\n"
                f"--- Prozess-Log ({log_file.name}) ---\n"
                f"{log_tail or '(keine Ausgabe)'}\n"
                f"--- Ende Prozess-Log ---"
            )
            _finalize_part_file(str(output_file))
            detail = f"\nDetails: {log_tail.splitlines()[-1]}" if log_tail else ""
            raise RuntimeError(
                f"Aufnahmeprozess (yt-dlp) ist direkt beim Start abgestürzt "
                f"(Code {proc.returncode}).{detail}"
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

        with _instance_lock(instance_id):
            _write_instance_recording(instance_id, meta)

        # Hintergrund-Wächter starten, der spätere Start-Abstürze (z. B. nach
        # 2-4s während der YouTube-Extraktion) sofort abfängt und loggt
        watcher = threading.Thread(
            target=_watch_recording_process,
            args=(proc, instance_id, str(output_file), log_file),
            daemon=True,
        )
        watcher.start()

        log(f"start_recording ({instance_id}): Aufnahme läuft (PID {proc.pid}).")
        return meta

    except Exception as e:
        log(f"start_recording ({instance_id}) fehlgeschlagen: {e}")
        raise


def stop_recording(instance_id: str = "default") -> bool:
    try:
        _ensure_dirs()
        active = get_active_recording(instance_id)
        if not active:
            with _instance_lock(instance_id):
                _write_instance_recording(instance_id, None)
            log(f"stop_recording ({instance_id}): Keine aktive Aufnahme gefunden.")
            return False

        pid = active.get("pid")
        output_file = active.get("output_file")
        log_file = active.get("log_file")
        stem = Path(str(output_file)).stem if output_file else ""

        # In der State-Datei markieren, dass ein regulärer Stopp läuft, damit
        # _watch_recording_process dies nicht als unerwarteten Absturz wertet.
        with _instance_lock(instance_id):
            active["stopping"] = True
            _write_instance_recording(instance_id, active)

        if not isinstance(pid, int) or not _is_recording_process_alive(pid, output_file):
            _finalize_part_file(output_file)
            with _instance_lock(instance_id):
                _write_instance_recording(instance_id, None)
            return False

        try:
            # Sanftes SIGINT direkt an yt-dlp senden, damit yt-dlp seinerseits ffmpeg
            # sauber beendet und das Muxen / Finalisieren des MP4-Containers abschließt.
            os.kill(pid, signal.SIGINT)
            log(f"stop_recording ({instance_id}): SIGINT an PID {pid} gesendet.")
        except Exception as e:
            log(f"stop_recording ({instance_id}): Fehler bei SIGINT an PID {pid}: {e}")

        # Bis zu 15 Sekunden (150 * 0.1s) warten, bis SOWOHL yt-dlp ALS AUCH
        # nachgelagerte ffmpeg-Muxing/Fixup-Prozesse (die .temp.mp4 schreiben)
        # regulär beendet sind!
        for _ in range(150):
            time.sleep(0.1)
            if not _is_recording_process_alive(pid, output_file) and not _is_any_helper_alive_for_stem(stem):
                break

        # Falls nach 15 Sekunden noch Prozesse (yt-dlp oder ffmpeg) hängen -> SIGTERM
        if _is_recording_process_alive(pid, output_file) or _is_any_helper_alive_for_stem(stem):
            try:
                log(f"stop_recording ({instance_id}): Prozessgruppe/Helfer für PID {pid} läuft noch, sende SIGTERM.")
                _kill_recording_tree(pid, signal.SIGTERM)
                _kill_helpers_for_stem(stem, signal.SIGTERM)
            except Exception as e:
                log(f"stop_recording ({instance_id}): Fehler bei SIGTERM: {e}")

            for _ in range(25):
                time.sleep(0.1)
                if not _is_recording_process_alive(pid, output_file) and not _is_any_helper_alive_for_stem(stem):
                    break

        # Falls immer noch am Leben -> SIGKILL
        if _is_recording_process_alive(pid, output_file) or _is_any_helper_alive_for_stem(stem):
            try:
                log(f"stop_recording ({instance_id}): Sende SIGKILL an Prozessgruppe/Helfer für PID {pid}.")
                _kill_recording_tree(pid, signal.SIGKILL)
                _kill_helpers_for_stem(stem, signal.SIGKILL)
            except Exception as e:
                log(f"stop_recording ({instance_id}): Fehler bei SIGKILL: {e}")
            time.sleep(0.3)
            _reap_zombie_if_child(pid)

        # Kurze Pause, damit das Betriebssystem alle Dateideskriptoren geschlossen hat,
        # und anschließend sämtliche .temp.mp4 / .mp4.part Dateien sauber auflösen.
        time.sleep(0.4)
        _finalize_part_file(output_file)

        out_path = Path(str(output_file)) if output_file else None
        if out_path and out_path.exists() and out_path.stat().st_size > 0:
            log(f"stop_recording ({instance_id}): Aufnahme erfolgreich abgeschlossen -> {out_path.name} ({out_path.stat().st_size} Bytes).")
        else:
            log_tail = _read_log_tail(log_file)
            log(
                f"stop_recording ({instance_id}): WARNUNG – Keine gültige Ausgabedatei "
                f"({output_file}) nach dem Stoppen vorhanden!\n"
                f"--- Prozess-Log ---\n{log_tail or '(leer)'}\n--- Ende Prozess-Log ---"
            )

        with _instance_lock(instance_id):
            _write_instance_recording(instance_id, None)
        return True

    except Exception as e:
        log(f"Unerwarteter Fehler in stop_recording ({instance_id}): {e}\n{traceback.format_exc()}")
        try:
            with _instance_lock(instance_id):
                _write_instance_recording(instance_id, None)
        except Exception:
            pass
        return False


def stop_all_recordings() -> None:
    """
    Beendet alle laufenden Aufnahmen auf sämtlichen Monitoren und räumt alle
    State-Dateien sauber auf (z. B. beim Beenden von CamWall).
    """
    _ensure_dirs()
    instance_ids = {path.stem for path in ACTIVE_RECORDING_DIR.glob("*.json")}
    instance_ids.update({"left", "right", "default"})
    for instance_id in sorted(instance_ids):
        try:
            if is_recording_active(instance_id):
                stop_recording(instance_id)
            else:
                with _instance_lock(instance_id):
                    _write_instance_recording(instance_id, None)
        except Exception as e:
            log(f"Fehler beim Stoppen der Aufnahme ({instance_id}): {e}")


def take_screenshot(url: str, title: str, browser: Optional[str] = None) -> Path:
    _ensure_dirs()
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    safe_title = _safe_title_for_filename(title)
    output_file = RECORDINGS_DIR / f"{ts}_{safe_title}.png"

    cmd_ytdlp = ["yt-dlp", "-g", "-f", "best", url]
    stype = _get_stream_type(url)
    if stype == "youtube_cookies" and browser:
        cmd_ytdlp[1:1] = ["--cookies-from-browser", browser]

    try:
        direct_url = subprocess.check_output(cmd_ytdlp, text=True).strip().split('\n')[0]
        if not direct_url:
            raise ValueError("Konnte direkte URL nicht auflösen")

        cmd_ffmpeg = [
            "ffmpeg", "-y",
            "-i", direct_url,
            "-vframes", "1",
            "-q:v", "2",
            str(output_file)
        ]
        subprocess.run(cmd_ffmpeg, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return output_file
    except Exception as e:
        log(f"Screenshot fehlgeschlagen: {e}")
        raise RuntimeError(f"Screenshot fehlgeschlagen: {e}")

if __name__ == "__main__":
    _ensure_dirs()
    cleanup_files()
