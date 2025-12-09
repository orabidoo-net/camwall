from typing import Dict, Any

from modules import config_loader


class ConfigService:
    def __init__(self):
        self.config: Dict[str, Any] = config_loader.load_config()

    def load_config(self) -> Dict[str, Any]:
        self.config = config_loader.load_config()
        return self.config

    def save_config(self, cfg: Dict[str, Any] | None = None) -> None:
        if cfg is not None:
            self.config = cfg
        config_loader.save_config(self.config)

    def get_streams(self) -> Dict[str, Dict[str, Any]]:
        return self.config.setdefault("streams", {})

    def get_monitors(self) -> Dict[str, Dict[str, Any]]:
        return self.config.setdefault("monitors", {})

    def update_stream(self, stream_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        self.validate_stream_id(stream_id)
        streams = self.get_streams()
        streams[stream_id] = data
        return data

    def delete_stream(self, stream_id: str) -> None:
        self.validate_stream_id(stream_id)
        streams = self.get_streams()
        if stream_id in streams:
            del streams[stream_id]

    def assign_stream_to_monitor(self, monitor_id: str, stream_id: str) -> Dict[str, Any]:
        self.validate_monitor_id(monitor_id)
        monitor = self._ensure_monitor(monitor_id)
        monitor["stream_id"] = stream_id
        return monitor

    def set_overlay_autostart(self, monitor_id: str, flag: bool) -> None:
        self.validate_monitor_id(monitor_id)
        monitor = self._ensure_monitor(monitor_id)
        monitor["overlay_autostart"] = bool(flag)

    def clear_stream_from_monitors(self, stream_id: str) -> None:
        monitors = self.get_monitors()
        for _, mconf in monitors.items():
            if mconf.get("stream_id") == stream_id:
                mconf["stream_id"] = "none"

    def validate_stream_id(self, stream_id: str) -> None:
        if not stream_id:
            raise ValueError("Ungültige Stream-ID.")

    def validate_monitor_id(self, monitor_id: str) -> None:
        if not monitor_id:
            raise ValueError("Ungültige Monitor-ID.")

    def _ensure_monitor(self, monitor_id: str) -> Dict[str, Any]:
        monitors = self.get_monitors()
        if monitor_id not in monitors:
            monitors[monitor_id] = {
                "name": monitor_id,
                "geometry": "",
                "stream_id": "none",
                "overlay_autostart": False,
            }
        return monitors[monitor_id]
