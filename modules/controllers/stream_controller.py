from typing import Dict, Tuple, List

from modules.services.config_service import ConfigService
from modules.services.preview_service import PreviewService


class StreamController:
    def __init__(self, main_window, config_service: ConfigService, preview_service: PreviewService):
        self.main_window = main_window
        self.config_service = config_service
        self.preview_service = preview_service

    def get_sorted_streams(self) -> List[Tuple[str, Dict]]:
        streams = self.config_service.get_streams()
        return sorted(streams.items(), key=lambda item: item[1].get("name", item[0]).lower())

    def add_stream(self, name: str, url: str, stype: str, browser: str, location: str = "", timezone: str = "") -> Tuple[str, Dict]:
        name = (name or "").strip()
        url = (url or "").strip()
        browser = (browser or "").strip()
        location = (location or "").strip()
        timezone = (timezone or "").strip()
        stype = stype or "direct"

        self._validate_stream_fields(name, url, stype, browser)

        base_id = self._make_stream_id_from_name(name)
        sid = base_id
        i = 2
        streams = self.config_service.get_streams()
        while sid in streams:
            sid = f"{base_id}_{i}"
            i += 1

        conf = {
            "name": name,
            "url": url,
            "type": stype,
            "browser": browser,
            "location": location,
            "timezone": timezone,
        }
        self.config_service.update_stream(sid, conf)
        return sid, conf

    def edit_stream(self, sid: str, name: str, url: str, stype: str, browser: str, location: str = "", timezone: str = "") -> Dict:
        streams = self.config_service.get_streams()
        if sid not in streams:
            raise ValueError("Unbekannter Stream.")

        name = (name or "").strip()
        url = (url or "").strip()
        browser = (browser or "").strip()
        location = (location or "").strip()
        timezone = (timezone or "").strip()
        stype = stype or "direct"

        self._validate_stream_fields(name, url, stype, browser)

        conf = {
            "name": name,
            "url": url,
            "type": stype,
            "browser": browser,
            "location": location,
            "timezone": timezone,
        }
        self.config_service.update_stream(sid, conf)
        return conf

    def delete_stream(self, sid: str) -> None:
        streams = self.config_service.get_streams()
        if sid not in streams:
            raise ValueError("Stream existiert nicht.")
        self.config_service.delete_stream(sid)

    def preview_stream(self, sid: str) -> str:
        streams = self.config_service.get_streams()
        sconf = streams.get(sid)
        if not sconf:
            raise ValueError("Konfiguration für diesen Stream fehlt.")

        stype = sconf.get("type", "direct")
        url = (sconf.get("url") or "").strip()
        if not url:
            raise ValueError("Für diesen Stream ist keine URL hinterlegt.")

        try:
            if stype == "youtube_cookies":
                browser = sconf.get("browser", "firefox")
                final_url = self.preview_service.preview_stream_with_cookies(url, browser)
            elif stype == "youtube":
                final_url = self.preview_service.preview_stream_without_cookies(url)
            else:
                final_url = self.preview_service.preview_stream_direct(url)

        except FileNotFoundError:
            raise FileNotFoundError("yt-dlp ist nicht installiert.")

        if self.main_window.log:
            self.main_window.log(f"Preview: starte mpv mit URL={final_url}")
        title = f"Vorschau: {sconf.get('name', sid)}"
        try:
            mpv_cmd = self.preview_service.build_mpv_command(final_url, title)
            self.preview_service.launch_mpv(mpv_cmd)
        except FileNotFoundError:
            raise FileNotFoundError("mpv wurde nicht gefunden.")

        return final_url

    def _validate_stream_fields(self, name: str, url: str, stype: str, browser: str) -> None:
        if not name or not url:
            raise ValueError("Name und URL dürfen nicht leer sein.")
        if stype == "youtube_cookies" and not browser:
            raise ValueError("Für YouTube mit Cookies muss ein Browser angegeben werden (z. B. firefox).")

    def _make_stream_id_from_name(self, name: str) -> str:
        base = (
            name.strip()
            .lower()
            .replace(" ", "_")
            .replace("ä", "ae")
            .replace("ö", "oe")
            .replace("ü", "ue")
            .replace("ß", "ss")
        )
        allowed = "abcdefghijklmnopqrstuvwxyz0123456789_"
        base = "".join(ch for ch in base if ch in allowed) or "stream"
        return base
