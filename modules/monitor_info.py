from dataclasses import dataclass
from typing import Dict, Any

@dataclass
class MonitorConfig:
    id: str
    name: str
    geometry: str
    stream_id: str

def monitors_from_config(cfg: Dict[str, Any]) -> list[MonitorConfig]:
    """
    Baut aus der Config-Liste der Monitore eine Liste von MonitorConfig-Objekten.
    """
    result: list[MonitorConfig] = []
    monitors = cfg.get("monitors", {})
    for mid, mconf in monitors.items():
        result.append(MonitorConfig(
            id=mid,
            name=mconf.get("name", mid),
            geometry=mconf.get("geometry", ""),
            stream_id=mconf.get("stream_id", "none"),
        ))
    return result
