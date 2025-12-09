from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from modules import stream_recorder
from modules.services.media_service import MediaService


class RecorderController:
    def __init__(self, main_window, media_service: MediaService):
        self.main_window = main_window
        self.media_service = media_service

    def start_recording(self, sid: str, sconf: Dict, title: str) -> Dict:
        if not sconf:
            raise ValueError("Bitte zuerst einen Stream auswählen.")

        url = (sconf.get("url") or "").strip()
        if not url:
            raise ValueError("Für diesen Stream ist keine URL hinterlegt.")

        stype = sconf.get("type", "direct")
        browser = (sconf.get("browser", "") or "").strip()

        final_title = (title or "").strip() or sconf.get("name", sid)

        if stype == "youtube_cookies" and not browser:
            raise ValueError("Dieser Stream benötigt einen Browser für Cookies.")

        return stream_recorder.start_recording(url, final_title, browser if stype == "youtube_cookies" else None)

    def stop_recording(self) -> bool:
        return stream_recorder.stop_recording()

    def take_screenshot(self, sid: str, sconf: Dict, title: str) -> Path:
        if not sconf:
            raise ValueError("Bitte zuerst einen Stream auswählen.")

        url = (sconf.get("url") or "").strip()
        if not url:
            raise ValueError("Für diesen Stream ist keine URL hinterlegt.")

        stype = sconf.get("type", "direct")
        browser = (sconf.get("browser", "") or "").strip()

        final_title = (title or "").strip() or sconf.get("name", sid)

        if stype == "youtube_cookies" and not browser:
            raise ValueError("Dieser Stream benötigt einen Browser für Cookies.")

        return stream_recorder.take_screenshot(
            url,
            final_title,
            browser if stype == "youtube_cookies" else None,
        )

    def load_media_list(self) -> Tuple[List[Tuple[str, str, str, str]], int]:
        files = self.media_service.list_recordings()
        entries: List[Tuple[str, str, str, str]] = []
        total_bytes = 0
        for p in files:
            try:
                st = p.stat()
            except FileNotFoundError:
                continue
            total_bytes += st.st_size
            size_str = self.media_service.get_human_size(st.st_size)
            mtime_str = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
            entries.append((str(p), p.name, mtime_str, size_str))

        return entries, total_bytes

    def delete_media_file(self, media_path: Path) -> None:
        self.media_service.delete_recording(media_path)

    def rename_media_file(self, media_path: Path, new_name: str) -> Path:
        return self.media_service.rename_recording(media_path, new_name)

    def cleanup_recordings(self) -> Tuple[List[str], int]:
        return self.media_service.cleanup_temp_recordings()

    def open_media_file(self, media_path: Path) -> None:
        self.media_service.open_recording(media_path)

    def open_media_folder(self) -> None:
        self.media_service.open_recording_folder()
