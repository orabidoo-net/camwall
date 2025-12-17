import copy
import json
from typing import Dict, Any

from modules.paths import CONFIG_PATH

DEFAULT_CONFIG = {
    "streams": {},
    "monitors": {
        "left": {"stream_id": "none", "overlay_autostart": False},
        "right": {"stream_id": "none", "overlay_autostart": False},
    },
}


def _default_config() -> Dict[str, Any]:
    return copy.deepcopy(DEFAULT_CONFIG)


def load_config() -> Dict[str, Any]:
    cfg = _default_config()
    if not CONFIG_PATH.exists():
        return cfg

    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return cfg

    if isinstance(data, dict):
        cfg.update(data)

    monitors = cfg.setdefault("monitors", {})
    monitors.setdefault("left", {"stream_id": "none", "overlay_autostart": False})
    monitors.setdefault("right", {"stream_id": "none", "overlay_autostart": False})
    cfg.setdefault("streams", {})
    return cfg


def save_config(config: Dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)
