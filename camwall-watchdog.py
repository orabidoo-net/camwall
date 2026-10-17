#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import socket
import json
import subprocess
from pathlib import Path
from datetime import datetime

# Pfade
BASE_DIR = Path.home() / ".local" / "share" / "camwall"
CONFIG_FILE = BASE_DIR / "config.json"
SCHEDULE_FILE = BASE_DIR / "schedule.json"
LOG_FILE = BASE_DIR / "watchdog.log"
RUN_FILE = Path("/tmp/camwall_active")

def log(msg: str):
    try:
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass

def load_json(filepath: Path) -> dict | list:
    if not filepath.exists():
        return {} if filepath == CONFIG_FILE else []
    try:
        with filepath.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"Fehler beim Lesen von {filepath.name}: {e}")
        return {} if filepath == CONFIG_FILE else []

def save_config(config: dict):
    try:
        with CONFIG_FILE.open("w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        log(f"Fehler beim Speichern der Config: {e}")

def _resolve_apply_target() -> list[str]:
    candidates = [
        Path(__file__).resolve().with_name("camwall-apply.py"),
        Path("/usr/local/bin/camwall-apply"),
        Path("/opt/camwall/camwall-apply.py"),
    ]
    apply_path = next((p for p in candidates if p.exists()), None)
    if not apply_path:
        return ["camwall-apply"]
    if apply_path.suffix == ".py":
        return [sys.executable, str(apply_path)]
    return [str(apply_path)]

def _resolve_overlay_target() -> list[str]:
    candidates = [
        Path(__file__).resolve().with_name("camwall-overlay.py"),
        Path(__file__).resolve().with_name("camwall-overlay"),
        Path("/usr/local/bin/camwall-overlay"),
        Path("/opt/camwall/camwall-overlay.py"),
    ]
    overlay_path = next((p for p in candidates if p.exists()), None)
    if not overlay_path:
        return ["camwall-overlay"]
    if overlay_path.suffix == ".py":
        return [sys.executable, str(overlay_path)]
    return [str(overlay_path)]

def is_stream_alive(monitor_id: str) -> bool:
    sock_path = f"/tmp/camwall_{monitor_id}.sock"
    if not os.path.exists(sock_path):
        return False
        
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(2.0)
        client.connect(sock_path)
        
        msg = json.dumps({"command": ["get_property", "time-pos"]}) + "\n"
        client.sendall(msg.encode('utf-8'))
        
        response = client.recv(1024)
        client.close()
        return bool(response)
    except Exception:
        return False

def restart_monitor(monitor_id: str, mconf: dict, reason: str = "Gesundheitscheck"):
    log(f"{reason}: Starte Stream auf Monitor '{monitor_id}' neu...")
    
    try:
        apply_cmd = _resolve_apply_target()
        apply_cmd.append(monitor_id)
        subprocess.Popen(apply_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log(f"Fehler beim Neustart des Hintergrunds ({monitor_id}): {e}")

    if mconf.get("overlay_autostart"):
        time.sleep(2)
        try:
            subprocess.run(["pkill", "-f", f"camwall-overlay.*{monitor_id}"], check=False)
            overlay_cmd = _resolve_overlay_target()
            overlay_cmd.append(monitor_id)
            subprocess.Popen(overlay_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            log(f"Fehler beim Neustart des Overlays ({monitor_id}): {e}")

def main():
    log("Watchdog gestartet. Warte auf Aktivierung durch die GUI...")
    executed_schedules = {}  # Speichert, was heute schon ausgeführt wurde (ID -> Datum)
    
    while True:
        # Wenn CamWall "ausgeschaltet" ist (keine Startdatei), dann ignoriere auch die Zeitpläne
        if not RUN_FILE.exists():
            time.sleep(10)
            continue
            
        config = load_json(CONFIG_FILE)
        schedules = load_json(SCHEDULE_FILE)
        
        current_date = datetime.now().strftime("%Y-%m-%d")
        current_time = datetime.now().strftime("%H:%M")
        
        config_changed = False
        restarted_monitors = set()
        
        # 1. ZEITPLAN PRÜFEN
        for sched in schedules:
            if not sched.get("active", True):
                continue
                
            sched_time = sched.get("time")
            sched_id = sched.get("id")
            
            # Ist es Zeit und wurde dieser Plan heute noch nicht ausgeführt?
            if sched_time == current_time and executed_schedules.get(sched_id) != current_date:
                mon_id = sched.get("monitor")
                new_stream = sched.get("stream_id")
                
                log(f"Zeitplan-Event ausgelöst: Wechsle Monitor '{mon_id}' auf '{new_stream}'")
                
                # Config im Speicher anpassen
                if "monitors" not in config:
                    config["monitors"] = {}
                if mon_id not in config["monitors"]:
                    config["monitors"][mon_id] = {}
                    
                config["monitors"][mon_id]["stream_id"] = new_stream
                config_changed = True
                
                # Als 'heute erledigt' markieren
                executed_schedules[sched_id] = current_date
                restarted_monitors.add(mon_id)

        # Wenn der Zeitplan zugeschlagen hat, müssen wir die Config auf der Festplatte speichern,
        # damit camwall-apply gleich die neuen Werte lesen kann.
        if config_changed:
            save_config(config)
            
        # Monitore neu starten, die vom Zeitplan betroffen waren
        for mon_id in restarted_monitors:
            restart_monitor(mon_id, config["monitors"].get(mon_id, {}), reason="Zeitplan")
        
        # 2. GESUNDHEITSCHECK (nur für Monitore, die wir nicht gerade erst neu gestartet haben)
        monitors = config.get("monitors", {})
        for monitor_id, mconf in monitors.items():
            if monitor_id in restarted_monitors:
                continue # Diesen haben wir gerade erst gestartet, der muss nicht geprüft werden
                
            stream_id = mconf.get("stream_id", "none")
            
            if stream_id != "none":
                if not is_stream_alive(monitor_id):
                    restart_monitor(monitor_id, mconf, reason="Stream tot")
                    time.sleep(5) # Kurze Atempause für das System
                    
        # Schlafzyklus bis zur nächsten Prüfung
        time.sleep(30)

if __name__ == "__main__":
    main()
