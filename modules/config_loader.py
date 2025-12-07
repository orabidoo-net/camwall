import json
import os

CONFIG_PATH = os.path.expanduser("~/.config/camwall/config.json")

def load_config():
    """Lädt die Camwall-Konfiguration."""
    if not os.path.exists(CONFIG_PATH):
        return {"monitors": {}}

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[config_loader] Fehler beim Laden der Konfiguration: {e}")
        return {"monitors": {}}

def save_config(config):
    """Speichert die Camwall-Konfiguration."""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        print(f"[config_loader] Fehler beim Speichern der Konfiguration: {e}")
