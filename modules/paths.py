from pathlib import Path

BASE_DIR = Path.home() / ".local" / "share" / "camwall"
CONFIG_PATH = BASE_DIR / "config.json"
LOG_PATH = BASE_DIR / "camwall.log"
PID_DIR = BASE_DIR / "pids"

BASE_DIR.mkdir(parents=True, exist_ok=True)
PID_DIR.mkdir(parents=True, exist_ok=True)
