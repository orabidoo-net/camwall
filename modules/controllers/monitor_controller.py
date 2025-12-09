from typing import Dict, List, Tuple

from modules.services.config_service import ConfigService


class MonitorController:
    def __init__(self, main_window, config_service: ConfigService):
        self.main_window = main_window
        self.config_service = config_service

    def get_monitors(self) -> List[Tuple[str, Dict]]:
        return list(self.config_service.get_monitors().items())

    def assign_stream(self, mon_id: str, stream_id: str, overlay_autostart: bool) -> Dict:
        monitor = self.config_service.assign_stream_to_monitor(mon_id, stream_id)
        self.config_service.set_overlay_autostart(mon_id, overlay_autostart)
        return monitor

    def clear_stream_from_monitors(self, stream_id: str) -> None:
        self.config_service.clear_stream_from_monitors(stream_id)

    def save_monitors(self) -> None:
        self.config_service.save_config()
